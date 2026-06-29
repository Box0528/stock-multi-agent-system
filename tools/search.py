import os
from datetime import datetime
from tavily import TavilyClient
from langchain_core.tools import tool

client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

def get_date_context() -> dict:
    now = datetime.now()
    return {
        "today": now.strftime("%Y年%m月%d日"),
        "year": now.strftime("%Y"),
        "month": now.strftime("%Y年%m月"),
    }

@tool
def search_stock_news(query: str, max_results: int = 5) -> str:
    """
    搜索股票相关新闻和公告。
    输入搜索关键词，返回最新的新闻摘要列表。
    适用于搜索个股新闻、行业动态、政策信息、机构评级等。
    """
    try:
        results = client.search(
            query=query,
            max_results=max_results,
            search_depth="advanced",
            days=7,  # 只搜索最近7天的新闻
        )

        if not results or "results" not in results:
            return f"未找到关于'{query}'的相关新闻。"

        date_ctx = get_date_context()
        output_lines = [
            f"搜索时间：{date_ctx['today']}",
            f"搜索关键词：{query}",
            f"时间范围：最近7天",
            f"共找到 {len(results['results'])} 条结果：\n"
        ]

        for i, item in enumerate(results["results"], 1):
            title = item.get("title", "无标题")
            url = item.get("url", "")
            content = item.get("content", "")[:300]
            published = item.get("published_date", "日期未知")

            output_lines.append(
                f"{i}. 【{title}】\n"
                f"   发布时间：{published}\n"
                f"   摘要：{content}\n"
                f"   链接：{url}\n"
            )

        return "\n".join(output_lines)

    except Exception as e:
        return f"搜索失败：{str(e)}"


@tool
def search_stock_news_today(query: str, max_results: int = 5) -> str:
    """
    搜索股票今日最新动态，只返回当天或最近24小时的新闻。
    用于获取盘中实时消息、当日公告、突发事件等极短期信息。
    """
    try:
        results = client.search(
            query=query,
            max_results=max_results,
            search_depth="advanced",
            days=1,  # 只搜索最近1天
        )

        if not results or "results" not in results:
            return f"今日暂无关于'{query}'的最新消息。"

        date_ctx = get_date_context()
        output_lines = [
            f"搜索时间：{date_ctx['today']}",
            f"搜索关键词：{query}",
            f"时间范围：最近24小时",
            f"共找到 {len(results['results'])} 条结果：\n"
        ]

        for i, item in enumerate(results["results"], 1):
            title = item.get("title", "无标题")
            url = item.get("url", "")
            content = item.get("content", "")[:300]
            published = item.get("published_date", "日期未知")

            output_lines.append(
                f"{i}. 【{title}】\n"
                f"   发布时间：{published}\n"
                f"   摘要：{content}\n"
                f"   链接：{url}\n"
            )

        return "\n".join(output_lines)

    except Exception as e:
        return f"搜索失败：{str(e)}"