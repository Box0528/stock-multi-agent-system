import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from config import get_llm
from tools.stock_data import analyze_sector
from tools.search import search_stock_news

llm = get_llm(temperature=0.1)
llm_with_tools = llm.bind_tools([analyze_sector, search_stock_news])


def get_system_prompt() -> str:
    today = datetime.now().strftime("%Y年%m月%d日")
    year = datetime.now().strftime("%Y")

    return f"""你是一位专业的板块分析师。今天是{today}。

你有两个工具：
- analyze_sector：计算指定行业板块的统计数据（上涨比例、资金流向、强度评分等）
- search_stock_news：搜索板块相关政策、热点新闻

分析一个板块时，必须按以下顺序完成3步：
1. 用analyze_sector获取板块统计数据
2. 用search_stock_news搜索"{{行业名称}} 政策 {year}"
3. 用search_stock_news搜索"{{行业名称}} 资金 龙头 {today[:7]}"

完成后输出以下格式报告：

## 板块分析报告（{today}）

### 板块强度评分：X / 100
（强：80+，中：50-80，弱：50以下）

### 量化统计
（上涨比例、平均涨幅、资金流向、均线多头占比）

### 板块龙头
（涨幅前3只，简要说明）

### 政策与热点
（近期政策催化、市场热点）

### 综合判断
- 板块当前强度：强 / 中 / 弱
- 资金参与度：高 / 中 / 低
- 操作建议：积极关注 / 观望 / 回避
- 判断依据：（2句话）
"""


def run_sector_analyst(industry_name: str, stock_name: str = "") -> str:
    """运行板块分析师Agent"""

    query = f"请分析【{industry_name}】板块的整体强弱和资金流向"
    if stock_name:
        query += f"，重点关注{stock_name}所在板块的机会"

    messages = [
        SystemMessage(content=get_system_prompt()),
        HumanMessage(content=query),
    ]

    for _ in range(8):
        response = llm_with_tools.invoke(messages)
        messages.append(response)

        if not response.tool_calls:
            return response.content

        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            print(f"[Sector Analyst] 调用（{tool_name}）：{tool_args}")

            if tool_name == "analyze_sector":
                result = analyze_sector.invoke(tool_args)
            elif tool_name == "search_stock_news":
                result = search_stock_news.invoke(tool_args)
            else:
                result = f"未知工具: {tool_name}"

            messages.append(ToolMessage(
                content=str(result),
                tool_call_id=tool_call["id"]
            ))

    return "分析超过最大轮次，请重试。"


if __name__ == "__main__":
    print("=== 板块分析师 Agent 测试 ===\n")
    result = run_sector_analyst(
        industry_name="计算机、通信和其他电子设备制造业",
        stock_name="有研新材"
    )
    print(result)