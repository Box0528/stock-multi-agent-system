"""Tool Receipts 式幻觉检测 —— 用确定性程序比对而非LLM判断来核验报告里的数字声明。

参考: "Tool Receipts, Not Zero-Knowledge Proofs: Practical Hallucination
Detection for AI Agents" (arXiv:2603.10060)。核心思路：Agent 调用工具时
完整记录"调用参数+原始返回结果"（收据），报告生成后用符号比对核对声明是否
能在收据里找到依据——校验环节不使用LLM，避免"用会幻觉的模型去判断幻觉"
的循环问题。

这是纯函数模块（不做I/O），方法论上的诚实边界：找不到依据的声明只标注
"未核验"，不武断判定为"编造"——可能是LLM基于真实数据做的衍生计算
（如百分比变化），程序化比对无法区分这两种情况。
"""

import re
from dataclasses import dataclass


# 两种模式：① 任意数字（含整数）+ 金融单位；② 小数点数字（无单位也捕获）
# 整数不带单位不捕获，避免把年份、序号等无关数字误判为财务声明
_NUMBER_PATTERN = re.compile(
    r'(\d+(?:\.\d+)?)\s*(元|%|亿|万|股|只|分|倍|点)'  # 数字 + 金融单位
    r'|'
    r'(\d+\.\d+)'                                      # 小数，无单位
)


@dataclass
class NumericClaim:
    value: str          # 原始数字字符串，如 "17.80"
    unit: str            # 单位，可能为空字符串
    context: str          # 数字前后的一小段文本，便于人工核查


def extract_numeric_claims(report_text: str) -> list[NumericClaim]:
    """从报告文本里抓取数字声明（整数+单位 或 小数）。"""
    claims = []
    for m in _NUMBER_PATTERN.finditer(report_text):
        if m.group(1) is not None:        # 匹配到 数字+单位 模式
            value, unit = m.group(1), m.group(2) or ""
        else:                              # 匹配到 纯小数 模式
            value, unit = m.group(3), ""
        start = max(0, m.start() - 10)
        end = min(len(report_text), m.end() + 5)
        context = report_text[start:end].replace("\n", " ").strip()
        claims.append(NumericClaim(value=value, unit=unit, context=context))
    return claims


def _value_in_receipts(value: str, receipts_text: str) -> bool:
    """检查数值是否能在收据文本里直接找到（允许末尾补0的精度差异，如 17.8 == 17.80）。"""
    if value in receipts_text:
        return True
    try:
        f = float(value)
    except ValueError:
        return False
    # 尝试常见精度变体：1位小数、2位小数、去掉末尾0的整数形式
    variants = {f"{f:.1f}", f"{f:.2f}"}
    if f == int(f):
        variants.add(str(int(f)))
    return any(v in receipts_text for v in variants)


def check_grounding(report_text: str, receipts: list[dict]) -> dict:
    """核对报告里的数字声明能否在工具调用收据里找到依据。

    receipts: [{"tool_name": str, "args": dict, "result": str}, ...]

    返回:
        {
            "total_claims": int,
            "grounded_count": int,
            "grounding_score": float,  # grounded_count / total_claims，无声明时为 1.0
            "ungrounded_claims": [NumericClaim, ...],
        }
    """
    receipts_text = "\n".join(r.get("result", "") for r in receipts)
    claims = extract_numeric_claims(report_text)

    if not claims:
        return {
            "total_claims": 0,
            "grounded_count": 0,
            "grounding_score": 1.0,
            "ungrounded_claims": [],
        }

    ungrounded = [c for c in claims if not _value_in_receipts(c.value, receipts_text)]
    grounded_count = len(claims) - len(ungrounded)

    return {
        "total_claims": len(claims),
        "grounded_count": grounded_count,
        "grounding_score": grounded_count / len(claims),
        "ungrounded_claims": ungrounded,
    }
