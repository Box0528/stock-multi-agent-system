import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
from langchain_core.messages import HumanMessage, SystemMessage
from config import get_llm
from core.cost_tracker import CostTracker

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一位投资研究规划师，负责在正式分析开始前，制定清晰的研究任务计划。

收到用户输入的股票后，你需要：
1. 明确本次研究的核心问题（用户最想知道什么）
2. 列出技术面、消息面、板块面各自需要重点关注的方向
3. 提示分析师需要特别注意的风险点

输出格式（简洁，供下游 Agent 参考）：

## 研究任务计划

**研究目标**：{一句话说明}

**技术面重点**：
- （例：重点看近期均线是否有效支撑、换手率是否异常）

**消息面重点**：
- （例：重点搜索近期公告、机构评级变化）

**板块面重点**：
- （例：重点看所在行业资金流向是否持续）

**特别风险提示**：
- （例：ST风险、大股东减持公告等）
"""


def run_planner(stock_name: str, industry: str = "", tracker: CostTracker = None) -> str:
    query = f"请为股票【{stock_name}】制定研究任务计划"
    if industry:
        query += f"，该股票属于【{industry}】行业"

    llm = get_llm(temperature=0.1)
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
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
