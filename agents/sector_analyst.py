import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
from datetime import datetime
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from config import get_llm
from tools.stock_data import analyze_sector
from tools.search import search_stock_news
from core.event_bus import ConsoleEventBus
from core.cost_tracker import CostTracker
from core.cognitive import parse_self_evaluation, strip_self_evaluation, SELF_EVAL_SUFFIX, AgentOutput
from core.resilience import retry_llm_call, retry_tool_call
from core.grounding import check_grounding

logger = logging.getLogger(__name__)

TOOL_MAP = {
    "analyze_sector": analyze_sector,
    "search_stock_news": search_stock_news,
}


def get_system_prompt() -> str:
    today = datetime.now().strftime("%Y年%m月%d日")
    year = datetime.now().strftime("%Y")

    return f"""# 角色
你是一位专注板块轮动的行业分析师，擅长识别资金流向和板块强弱切换。
你的核心理念：个股的涨跌70%取决于所在板块，板块强弱比个股技术面更重要。

# 工具
- analyze_sector：获取板块量化数据（上涨比例、均涨幅、资金流向、均线多头占比、强度评分0-100）
- search_stock_news：搜索板块政策和资金动态

# 分析方法论

## 第一步：量化板块体检
调用 analyze_sector 获取板块统计数据，从四个维度评分：
1. **涨跌面**：上涨比例>60%为强势，<40%为弱势
2. **资金面**：资金持续流入为积极，流出为消极
3. **技术面**：均线多头占比>50%为健康，<30%为恶化
4. **活跃度**：成交额是否放大（对比近5日均值）

## 第二步：政策催化扫描
调用 search_stock_news 搜索：
1. "{{行业名称}} 政策 {year}" — 是否有产业政策利好/利空
2. "{{行业名称}} 资金 龙头 {today[:7]}" — 近期资金动向

## 第三步：板块定位
判断当前板块处于轮动周期的哪个阶段：
- **启动期**：资金刚开始流入，涨幅不大但多头占比提升 → 最佳介入点
- **加速期**：资金大幅流入，板块全面上涨 → 可跟进但注意追高
- **高位期**：涨幅巨大但资金开始分歧 → 谨慎，随时可能转弱
- **退潮期**：资金流出，跌多涨少 → 回避

## 第四步：个股在板块中的位置
目标股票在板块中是龙头、跟风还是补涨？
- 龙头：涨幅靠前 + 成交额占比高
- 跟风：跟随板块涨跌但弹性小
- 补涨：板块已涨一段时间后才启动

## 绝对禁止
- 禁止只看板块强度评分就下结论（评分是综合指标，需拆解各维度）
- 禁止忽略板块轮动阶段（同样60分，启动期和高位期含义完全不同）
- 禁止在 analyze_sector 返回错误时编造数据
- 禁止修改用户提供的行业名称！调用 analyze_sector 时必须原样传入用户消息中方括号【】内的行业名称，不得翻译、缩写或替换

# 输出格式

## 板块分析报告（{today}）

### 板块强度评分：X / 100
（一句话定性：强势/中性/弱势）

### 四维体检
| 维度 | 数据 | 评估 |
|------|------|------|
| 涨跌面 | 上涨X只/下跌X只（上涨比例X%） | 强/中/弱 |
| 资金面 | 资金XXX | 积极/中性/消极 |
| 技术面 | 均线多头占比X% | 健康/一般/恶化 |
| 活跃度 | 今日成交额X亿 | 放量/平稳/缩量 |

### 板块龙头（涨幅前3）
（简要列出，注明涨幅和成交额）

### 轮动阶段判断
当前阶段：启动期 / 加速期 / 高位期 / 退潮期
判断依据：（2句话）

### 政策与催化
（近期政策面，标注来源和日期）

### 综合判断
- 板块当前强度：强 / 中 / 弱
- 轮动阶段：X期
- 目标股票板块定位：龙头 / 跟风 / 补涨 / 未入选
- 操作建议：积极关注 / 观望 / 回避
- 判断依据：（2句话，必须引用具体数据）
""" + SELF_EVAL_SUFFIX


def run_sector_analyst(
    industry_name: str,
    stock_name: str = "",
    bus=None,
    tracker: CostTracker = None,
    lessons: str = "",
) -> AgentOutput:
    if bus is None:
        bus = ConsoleEventBus()

    query = (
        f"请分析【{industry_name}】板块的整体强弱和资金流向。\n"
        f"⚠️ 调用 analyze_sector 时，industry_name 参数必须完整传入「{industry_name}」，"
        f"禁止修改、翻译或缩写。"
    )
    if stock_name:
        query += f"\n重点关注{stock_name}在该板块中的龙头/跟风/补涨定位。"

    system_content = get_system_prompt()
    if lessons:
        system_content += f"\n\n# 历史教训（基于复盘，本次必须调整策略）\n{lessons}"

    llm = get_llm(temperature=0.1)
    llm_with_tools = llm.bind_tools([analyze_sector, search_stock_news])
    messages = [
        SystemMessage(content=system_content),
        HumanMessage(content=query),
    ]
    receipts: list[dict] = []
    tool_called = False

    for _ in range(12):
        response = retry_llm_call(llm_with_tools, messages)
        messages.append(response)

        if tracker:
            usage = getattr(response, "usage_metadata", None) or {}
            tracker.record_llm_call(
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
            )

        if not response.tool_calls:
            if not tool_called:
                messages.append(HumanMessage(content="请先调用工具获取板块数据，再输出分析报告。"))
                continue
            raw_report = response.content
            confidence, details = parse_self_evaluation(raw_report)
            clean_report = strip_self_evaluation(raw_report)
            grounding = check_grounding(clean_report, receipts)
            return AgentOutput(
                report=clean_report,
                confidence=confidence,
                confidence_details=details,
                grounding_score=grounding["grounding_score"],
                ungrounded_claims=grounding["ungrounded_claims"],
            )

        tool_called = True
        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            bus.emit_tool_call("sector", f"🔧 {tool_name}({tool_args})")

            tool_fn = TOOL_MAP.get(tool_name)
            if tool_fn:
                result = retry_tool_call(tool_fn, tool_args, tool_name)
                receipts.append({"tool_name": tool_name, "args": tool_args, "result": str(result)})
                if tracker:
                    tracker.record_tool_call()
                    if tool_name == "search_stock_news":
                        tracker.record_search_call()
            else:
                result = f"未知工具: {tool_name}"

            messages.append(ToolMessage(content=str(result), tool_call_id=tool_call["id"]))

    return AgentOutput(report="分析超过最大轮次，请重试。", confidence=0.1)
