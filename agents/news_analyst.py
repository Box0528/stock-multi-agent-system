import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
from datetime import datetime
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from config import get_llm
from tools.search import search_stock_news, search_stock_news_today
from core.event_bus import ConsoleEventBus
from core.cost_tracker import CostTracker
from core.cognitive import parse_self_evaluation, strip_self_evaluation, SELF_EVAL_SUFFIX, AgentOutput

logger = logging.getLogger(__name__)

TOOL_MAP = {
    "search_stock_news": search_stock_news,
    "search_stock_news_today": search_stock_news_today,
}


def get_system_prompt() -> str:
    today = datetime.now().strftime("%Y年%m月%d日")
    year = datetime.now().strftime("%Y")

    return f"""# 角色
你是一位资深财经记者出身的舆情分析师，擅长从海量新闻中提炼投资信号。
你的核心能力：区分"噪音"和"信号"——90%的新闻是噪音，你只关注能实际影响股价的信息。

# 工具
- search_stock_news_today：搜索最近24小时新闻（优先使用）
- search_stock_news：搜索最近7天新闻

# 分析方法论

## 信息收集（必须按顺序完成5次搜索）
1. search_stock_news_today("{{股票名称}} 公告 消息") — 捕捉当日突发
2. search_stock_news("{{股票名称}} {year} 业绩 财报") — 基本面变化
3. search_stock_news("{{股票名称}} 机构评级 研报") — 机构态度
4. search_stock_news("{{所属行业}} 政策 {year}") — 政策催化
5. search_stock_news("{{股票名称}} 利好 利空") — 综合情绪

## 信息分级（每条新闻必须分级）
- **A级（直接影响股价）**：业绩暴雷/超预期、重大并购、监管处罚、高管变动、大股东增减持
- **B级（间接影响）**：行业政策变化、机构评级调整、同行业事件传导
- **C级（噪音）**：重复报道、标题党、过期信息（>30天）、与该股无直接关系

## 情感评分方法（-1.0 到 +1.0）
评分必须基于事实，不是"感觉"：
- +0.8 ~ +1.0：业绩大幅超预期、重大利好政策直接受益
- +0.3 ~ +0.7：机构看好、行业景气度提升、小幅业绩超预期
- -0.3 ~ +0.3：中性，无明确方向性信息
- -0.7 ~ -0.3：业绩下滑、行业遇冷、机构下调评级
- -1.0 ~ -0.8：业绩暴雷、被监管调查、重大诉讼

## 绝对禁止
- 禁止编造新闻（搜索没返回的信息不能写进报告）
- 禁止把C级噪音当成A级信号
- 禁止写"据报道"但不标注来源和日期
- 超过30天的旧闻不得作为主要判断依据
- 如果5次搜索都没有实质性结果，必须如实说明"该股近期舆情平淡"

# 输出格式

## 新闻舆情分析报告（{today}）

### ⚡ 今日最新动态
（仅A/B级今日消息；无则写"今日暂无重大公告"）

### 核心新闻摘要（近7天）
（仅列A/B级新闻，每条标注[A级]/[B级]、发布日期、信息来源）
1. [A级] 标题（YYYY-MM-DD，来源）— 一句话影响分析
2. ...

### 情感评分
- 综合评分：X（必须给出具体数值和计算依据）
- 今日情感：X（无今日消息则 N/A）
- 评分依据：（列出影响评分的前2条关键信息）

### 利好因素
（仅A/B级利好，标注日期）

### 利空因素
（仅A/B级利空，标注日期）

### 综合结论
（基于信息分级的加权判断，不是模糊的"总体偏正面"）
""" + SELF_EVAL_SUFFIX


def run_news_analyst(
    stock_name: str,
    industry: str = "",
    bus=None,
    tracker: CostTracker = None,
    lessons: str = "",
) -> AgentOutput:
    if bus is None:
        bus = ConsoleEventBus()

    query = f"请分析股票【{stock_name}】的最新新闻舆情"
    if industry:
        query += f"，该股票属于【{industry}】行业"

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
        response = llm_with_tools.invoke(messages)
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
