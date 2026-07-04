"""
复盘闭环核心模块 — 数据结构 + I/O，不含任何 LLM 调用。

职责边界：
  - 存储每次扫描推荐的"可验证预测"（股票、方向、推荐价、到期日）
  - 读写 meta/pending_reviews.json 和 meta/review_results.json
  - 计算 accuracy summary（纯统计，不经过 LLM）

不在这里做的事：
  - 解析 final_report 文本（由 scan_workflow 调用 memory.extraction）
  - 抓取价格（由 scripts/check_reviews.py 负责）
  - 把 summary 注入 prompt（由 scan_workflow 负责）
"""

from __future__ import annotations

import json
import os
import logging
from dataclasses import dataclass, asdict
from datetime import date, datetime
from typing import Literal

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
META_DIR = os.path.join(BASE_DIR, "meta")
PENDING_FILE = os.path.join(META_DIR, "pending_reviews.json")
RESULTS_FILE = os.path.join(META_DIR, "review_results.json")

Direction = Literal["bullish", "bearish", "neutral"]


@dataclass
class PendingReview:
    scan_id: str           # 唯一键：scan_date_code_checktype
    scan_date: str         # 推荐日期 YYYY-MM-DD
    review_date: str       # 到期验证日期 YYYY-MM-DD
    stock_code: str        # sh.600000 格式
    stock_name: str
    direction: Direction   # 推荐方向：bullish/bearish/neutral
    price_at_scan: float   # 推荐时收盘价
    source_advice: str     # 原始操作建议文字（买入/观望/回避）
    check_type: str = "t5"     # "t1"=次日 / "t5"=5交易日后
    source: str = "scan"       # "scan"=模式一 / "research"=模式二单股


@dataclass
class ReviewResult:
    scan_id: str
    scan_date: str
    review_date: str
    stock_code: str
    stock_name: str
    direction: Direction
    price_at_scan: float
    price_at_review: float
    return_pct: float      # (price_at_review - price_at_scan) / price_at_scan * 100
    direction_correct: bool
    counted_in_stats: bool
    check_type: str = "t5"
    source: str = "scan"


# ── 方向映射 ────────────────────────────────────────────────────

def advice_to_direction(advice: str) -> Direction:
    if advice in ("买入",):
        return "bullish"
    if advice in ("回避",):
        return "bearish"
    return "neutral"


def direction_correct(direction: Direction, return_pct: float) -> tuple[bool, bool]:
    """返回 (direction_correct, counted_in_stats)。neutral 不计入统计。

    阈值与 server.py reflection 保持一致：
      bullish 正确：实际涨幅 > +3%
      bearish 正确：实际跌幅 < -3%
    排除 ±3% 以内的噪声波动，避免虚高准确率。
    """
    if direction == "neutral":
        return False, False
    correct = (direction == "bullish" and return_pct > 3) or \
              (direction == "bearish" and return_pct < -3)
    return correct, True


# ── I/O ─────────────────────────────────────────────────────────

def _load_json(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("读取 %s 失败：%s", path, e)
        return default


def _save_json(path: str, data) -> None:
    os.makedirs(META_DIR, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)  # 原子替换，避免写入中途崩溃导致文件损坏


def load_pending() -> list[dict]:
    return _load_json(PENDING_FILE, [])


def save_pending(records: list[dict]) -> None:
    _save_json(PENDING_FILE, records)


def append_pending(new_records: list[PendingReview]) -> None:
    existing = load_pending()
    existing_ids = {r["scan_id"] for r in existing}
    for r in new_records:
        if r.scan_id not in existing_ids:
            existing.append(asdict(r))
    save_pending(existing)


def load_results() -> list[dict]:
    return _load_json(RESULTS_FILE, [])


def append_results(new_results: list[ReviewResult]) -> None:
    existing = load_results()
    existing_ids = {r["scan_id"] for r in existing}
    for r in new_results:
        if r.scan_id not in existing_ids:
            existing.append(asdict(r))
    _save_json(RESULTS_FILE, existing)


def pop_due_pending(as_of: str | None = None) -> tuple[list[dict], list[dict]]:
    """把到期的 pending 记录分出来，返回 (due, remaining)。"""
    today = as_of or date.today().isoformat()
    all_pending = load_pending()
    due = [r for r in all_pending if r["review_date"] <= today]
    remaining = [r for r in all_pending if r["review_date"] > today]
    return due, remaining


# ── Accuracy summary ────────────────────────────────────────────

def _acc_block(records: list[dict], label: str) -> list[str]:
    """计算一组记录的准确率，返回格式化文本行。"""
    counted = [r for r in records if r.get("counted_in_stats")]
    if not counted:
        return []
    total = len(counted)
    correct = sum(1 for r in counted if r["direction_correct"])
    bullish = [r for r in counted if r["direction"] == "bullish"]
    bearish = [r for r in counted if r["direction"] == "bearish"]
    bull_acc = (sum(1 for r in bullish if r["direction_correct"]) / len(bullish) * 100) if bullish else None
    bear_acc = (sum(1 for r in bearish if r["direction_correct"]) / len(bearish) * 100) if bearish else None
    lines = [f"  {label}：{correct/total*100:.0f}%（{correct}/{total}）"
             + (f"  看多{bull_acc:.0f}%" if bull_acc is not None else "")
             + (f"  看空{bear_acc:.0f}%" if bear_acc is not None else "")]
    return lines


def build_accuracy_summary(last_n: int = 20) -> str:
    """
    从最近 last_n 条有效结果里计算方向准确率（T+1 / T+5 分开展示），
    返回一段可直接注入 prompt 的中文文字。纯统计，不调 LLM。
    """
    results = load_results()
    if not results:
        return ""

    recent = results[-last_n:]
    t1 = [r for r in recent if r.get("check_type", "t5") == "t1"]
    t5 = [r for r in recent if r.get("check_type", "t5") == "t5"]

    lines_t1 = _acc_block(t1, "次日验证")
    lines_t5 = _acc_block(t5, "5交易日验证")
    if not lines_t1 and not lines_t5:
        return ""

    lines = [f"【历史复盘参考（最近 {len(recent)} 条）】"]
    lines += lines_t1
    lines += lines_t5
    lines.append("注：供参考，不作为本次决策的硬约束。")
    return "\n".join(lines)
