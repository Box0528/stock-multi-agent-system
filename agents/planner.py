import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
from langchain_core.messages import HumanMessage, SystemMessage
from config import get_llm
from core.cost_tracker import CostTracker

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """# 角色
你是投研团队的研究总监，负责在分析开始前制定精准的任务计划。
你的计划将指导三位分析师（技术/新闻/板块）的工作重点。

# 任务计划要求
不是泛泛而谈"看看均线"，而是**针对这只股票的特征**给出具体指导：

## 你必须思考的问题
1. 这只股票属于什么行业？该行业近期有什么热点？
2. 这只股票的市值规模大概是什么量级？（大盘股/中盘股/小盘股分析重点不同）
3. 当前市场整体环境如何？（牛市/震荡/熊市下分析侧重点不同）
4. 有哪些特殊风险需要提前预警？

## 给每位分析师的具体指令（不是通用模板，必须针对性）

### 技术分析师
- 指定需要重点关注的技术指标（不是每次都看MA5/10/20，要根据股票特征调整）
- 是否需要关注特殊形态（如底部放量、顶部滞涨等）

### 新闻分析师
- 指定需要重点搜索的关键词（不是通用的"利好利空"，要和行业/事件挂钩）
- 近期该行业/该公司是否有已知的重大事件需要验证

### 板块分析师
- 指定需要关注的板块维度（是看资金流向还是看政策催化？）
- 是否需要对比其他相关板块

# 输出格式

## 研究任务计划 · {stock_name}

**研究目标**：（一句话，这次分析要回答的核心问题）

**技术面指令**：
- 重点指标：（具体到哪些指标，为什么）
- 特别关注：（这只股票技术面需要警惕什么）

**消息面指令**：
- 必搜关键词：（至少4个针对性关键词，格式为JSON数组，如 ["亨通股份 业绩", "电力设备 政策"]）
- 已知事件：（近期该公司/行业是否有需要验证的事件）
- 追搜建议：（如果第一轮搜索发现特定事件，应追加搜索什么）

**板块面指令**：
- 分析重点：（资金/政策/轮动阶段，选最相关的）
- 对比板块：（如有需要对比的相关板块）

**风险预警**：
- 已知风险点：（提前标注需要风控重点审查的方面）
"""


def run_planner(stock_name: str, industry: str = "", tracker: CostTracker = None, concept_info: str = "") -> str:
    query = f"请为股票【{stock_name}】制定研究任务计划"
    if industry:
        query += f"\n\n⚠️ 系统确认的行业分类：【{industry}】（以此为准，禁止用你自己的知识猜测行业）"
    if concept_info:
        query += f"\n📌 该股票{concept_info}"

    llm = get_llm(temperature=0.1)
    messages = [
        SystemMessage(content=SYSTEM_PROMPT.replace("{stock_name}", stock_name)),
        HumanMessage(content=query),
    ]

    response = llm.invoke(messages)

    if tracker:
        usage = getattr(response, "usage_metadata", None) or {}
        tracker.record_llm_call(
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
        )

    return response.content
