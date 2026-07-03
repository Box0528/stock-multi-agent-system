import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import logging
from datetime import datetime
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from config import get_llm
from tools.search import search_stock_news, search_stock_news_today
from core.event_bus import ConsoleEventBus
from core.cost_tracker import CostTracker
from core.cognitive import parse_self_evaluation, strip_self_evaluation, SELF_EVAL_SUFFIX, AgentOutput
from core.resilience import retry_llm_call

logger = logging.getLogger(__name__)

TOOL_MAP = {
    "search_stock_news": search_stock_news,
    "search_stock_news_today": search_stock_news_today,
}


def get_system_prompt() -> str:
    today = datetime.now().strftime("%Y年%m月%d日")

    return f"""# 角色
你是一位资深财经记者出身的舆情分析师，擅长从海量新闻中提炼投资信号。
你的核心能力：区分"噪音"和"信号"——90%的新闻是噪音，你只关注能实际影响股价的信息。

# 工具
- search_stock_news_today：搜索最近24小时新闻（优先使用）
- search_stock_news：搜索最近7天新闻

# 分析方法论

## 搜索策略（自主制定关键词）
你必须主动规划搜索路径，无需外部指令：
1. 先用 search_stock_news_today 搜索今日最新动态（关键词：公司名称）
2. 根据行业特征自行组合 2-4 个有针对性的关键词，用 search_stock_news 深挖（例如："公司名 业绩"、"公司名 政策"、"行业名 监管"）
3. 如果发现重大事件线索，追加 1-2 次针对性深挖

## 时间约束（严格执行）
- 今天是 {today}，所有日期计算以此为基准
- 只引用上述工具返回的内容，禁止使用训练数据中的历史新闻
- 日期在 7 天内（{today} 往前 7 天）的新闻：正常引用
- 日期超过 7 天但不超过 30 天：必须在该条末尾加【历史参考，非近期】标注
- 日期超过 30 天：直接降为 C 级，不得写进正文报告
- 禁止将搜索结果之外的任何新闻或事件写入报告

## 信息分级（每条新闻必须分级）
- **A级（直接影响股价）**：业绩暴雷/超预期、重大并购、监管处罚、高管变动、大股东增减持
- **B级（间接影响）**：行业政策变化、机构评级调整、同行业事件传导
- **C级（噪音，不入报告）**：重复报道、标题党、过期信息（>30天）、与该股无直接关系

## 绝对禁止
- 禁止编造新闻（搜索没返回的信息不能写进报告）
- 禁止用你自己训练数据中的知识补充新闻（你只能引用搜索工具返回的内容）
- 禁止把C级噪音写进报告
- 禁止写"据报道"但不标注来源和日期
- 日期标注为"日期不明"的新闻不得作为主要判断依据
- 严格区分时间：近7天就是近7天，更早的标注为"历史参考"
- 禁止做情感评分（不要输出任何"情感评分"相关内容）

## 概念炒作判断（如有概念信息）
如果用户提供了该股票的概念板块信息，分析：
- 这些概念近期是否有市场炒作？（搜索相关概念热度）
- 股价上涨是基本面驱动还是概念炒作驱动？
- 概念退潮风险有多大？

# 输出格式

## 新闻舆情分析报告（{today}）

### ⚡ 今日最新动态
（仅A/B级今日消息；无则写"今日暂无重大公告"）

### 核心新闻摘要（近7天）
（仅列A/B级新闻，每条标注信息级别、日期、来源）
1. [A级] 标题（YYYY-MM-DD，来源）— 一句话：对股价的实际影响
2. ...

### 利好因素
（仅A/B级利好，标注日期，说明影响逻辑）

### 利空因素
（仅A/B级利空，标注日期，说明影响逻辑）

### 综合结论
- 消息面方向：利多 / 中性 / 利空
- 关键事件：（最影响股价的1-2件事）
- 风险点：（消息面需要警惕的风险）
""" + SELF_EVAL_SUFFIX


def run_news_analyst(
    stock_name: str,
    industry: str = "",
    bus=None,
    tracker: CostTracker = None,
    lessons: str = "",
    search_keywords: list[str] = None,
    price_context: str = "",
) -> AgentOutput:
    if bus is None:
        bus = ConsoleEventBus()

    query = f"请分析股票【{stock_name}】的最新新闻舆情"
    if industry:
        query += f"，该股票属于【{industry}】行业"

    if price_context:
        query += f"\n{price_context}"
    if search_keywords:
        query += f"\n\n## 消息面指令（来自研究总监）\n必搜关键词：{json.dumps(search_keywords, ensure_ascii=False)}"

    system_content = get_system_prompt()
    if lessons:
        system_content += f"\n\n# 历史教训（基于复盘，本次必须调整策略）\n{lessons}"

    llm = get_llm(temperature=0.1)
    llm_with_tools = llm.bind_tools([search_stock_news, search_stock_news_today])
    messages = [
        SystemMessage(content=system_content),
        HumanMessage(content=query),
    ]

    for _ in range(10):
        response = retry_llm_call(llm_with_tools, messages)
        messages.append(response)

        if tracker:
            usage = getattr(response, "usage_metadata", None) or {}
            tracker.record_llm_call(
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
            )

        if not response.tool_calls:
            raw_report = response.content
            confidence, details = parse_self_evaluation(raw_report)
            clean_report = strip_self_evaluation(raw_report)
            return AgentOutput(
                report=clean_report,
                confidence=confidence,
                confidence_details=details,
            )

        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            bus.emit_tool_call("news", f"🔍 {tool_name}({tool_args.get('query', '')})")

            tool_fn = TOOL_MAP.get(tool_name)
            if tool_fn:
                result = tool_fn.invoke(tool_args)
                if tracker:
                    tracker.record_tool_call()
                    if "search" in tool_name:
                        tracker.record_search_call()
            else:
                result = f"未知工具: {tool_name}"

            messages.append(ToolMessage(content=str(result), tool_call_id=tool_call["id"]))

    return AgentOutput(report="分析超过最大轮次，请重试。", confidence=0.1)
