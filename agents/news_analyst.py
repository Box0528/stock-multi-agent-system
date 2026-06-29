import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from config import get_llm
from tools.search import search_stock_news, search_stock_news_today

llm = get_llm(temperature=0.1)
llm_with_tools = llm.bind_tools([search_stock_news, search_stock_news_today])


def get_system_prompt() -> str:
    today = datetime.now().strftime("%Y年%m月%d日")
    year = datetime.now().strftime("%Y")

    return f"""你是一位专业的股票新闻分析师。今天是{today}。

你有两个搜索工具：
- search_stock_news_today：搜索最近24小时新闻，优先使用，捕捉当日最新消息
- search_stock_news：搜索最近7天新闻，用于了解近期整体动态

分析一只股票时，必须严格按以下顺序完成5次搜索：
1. 用search_stock_news_today搜索"{{股票名称}} 公告 消息"
2. 用search_stock_news搜索"{{股票名称}} {year} 业绩 财报"
3. 用search_stock_news搜索"{{股票名称}} 机构评级 研报"
4. 用search_stock_news搜索"{{所属行业}} 政策 {year}"
5. 用search_stock_news搜索"{{股票名称}} 利好 利空"

时间优先级规则：
- 今日消息 > 本周消息 > 本月消息
- 每条新闻必须注明发布日期
- 不得使用超过30天的旧消息作为主要判断依据
- 如果今日有重大公告，必须在报告开头单独列出

完成所有搜索后，输出以下格式报告：

## 新闻舆情分析报告（{today}）

### ⚡ 今日最新动态
（今日公告、盘中消息、突发事件；无则写"今日暂无重大公告"）

### 核心新闻摘要（近7天）
（列出3-5条最重要的新闻，每条注明发布日期）

### 情感评分
- 综合评分：X（-1到1之间，-1极度负面，0中性，1极度正面）
- 今日情感：X（仅基于今日消息评分，无今日消息则写"N/A"）
- 评分依据：（一句话说明）

### 利好因素
（列举2-3点，注明信息来源日期）

### 利空因素
（列举2-3点，注明信息来源日期）

### 综合结论
（2-3句话，明确说明短期和中期判断）
"""


def run_news_analyst(stock_name: str, industry: str = "") -> str:
    """运行新闻分析师Agent，返回新闻舆情分析报告"""

    query = f"请分析股票【{stock_name}】的最新新闻舆情"
    if industry:
        query += f"，该股票属于【{industry}】行业"

    messages = [
        SystemMessage(content=get_system_prompt()),
        HumanMessage(content=query),
    ]

    for _ in range(10):
        response = llm_with_tools.invoke(messages)
        messages.append(response)

        if not response.tool_calls:
            return response.content

        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            print(f"[News Analyst] 搜索（{tool_name}）：{tool_args.get('query', '')}")

            if tool_name == "search_stock_news":
                result = search_stock_news.invoke(tool_args)
            elif tool_name == "search_stock_news_today":
                result = search_stock_news_today.invoke(tool_args)
            else:
                result = f"未知工具: {tool_name}"

            messages.append(ToolMessage(
                content=str(result),
                tool_call_id=tool_call["id"]
            ))

    return "分析超过最大轮次，请重试。"


if __name__ == "__main__":
    print("=== 新闻分析师 Agent 测试 ===\n")
    result = run_news_analyst("有研新材", "半导体材料")
    print(result)