import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.messages import HumanMessage, SystemMessage
from config import get_llm
from tools.stock_data import run_stock_screener, get_stock_detail

# 绑定工具
llm = get_llm(temperature=0.1)
llm_with_tools = llm.bind_tools([run_stock_screener, get_stock_detail])

SYSTEM_PROMPT = """你是一位专业的股票技术分析师。
你有以下工具可以使用：
- run_stock_screener：运行量化选股模型，筛选出符合技术条件的股票池
- get_stock_detail：获取单只股票的详细技术指标

你的职责：
1. 调用选股工具获取今日股票池
2. 分析股票的技术面状况（均线、换手率、成交量）
3. 从技术角度给出买入建议和关注重点

输出格式要求：
- 用中文回答
- 先给出整体市场技术面判断
- 再列出重点关注股票（不超过5只）
- 每只股票给出技术面理由
"""


def run_technical_analyst(user_query: str) -> str:
    """运行技术分析师Agent，返回技术分析报告"""

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=user_query),
    ]

    # 最多循环5轮，直到LLM不再调用工具为止
    for _ in range(5):
        response = llm_with_tools.invoke(messages)
        messages.append(response)

        # 没有工具调用，说明LLM已经生成最终回答
        if not response.tool_calls:
            return response.content

        # 有工具调用，执行工具并把结果加入消息
        from langchain_core.messages import ToolMessage
        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            print(f"[Technical Analyst] 调用工具: {tool_name}，参数: {tool_args}")

            if tool_name == "run_stock_screener":
                result = run_stock_screener.invoke(tool_args)
            elif tool_name == "get_stock_detail":
                result = get_stock_detail.invoke(tool_args)
            else:
                result = f"未知工具: {tool_name}"

            messages.append(ToolMessage(
                content=str(result),
                tool_call_id=tool_call["id"]
            ))

    return "分析超过最大轮次，请重试。"

    # 第二轮：LLM根据工具结果生成最终分析
    final_response = llm_with_tools.invoke(messages)
    return final_response.content


if __name__ == "__main__":
    print("=== 技术分析师 Agent 测试 ===\n")
    result = run_technical_analyst("请分析今日市场技术面，给出值得关注的股票。")
    print(result)