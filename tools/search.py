import os
import logging
from datetime import datetime
from tavily import TavilyClient
from langchain_core.tools import tool
from core.cache import get_cached, set_cached

logger = logging.getLogger(__name__)

client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))


def get_date_context() -> dict:
    now = datetime.now()
    return {
        "today": now.strftime("%Y年%m月%d日"),
        "year": now.strftime("%Y"),
        "month": now.strftime("%Y年%m月"),
    }


def _search_with_cache(query: str, max_results: int, days: int, time_label: str) -> str:
    """统一的搜索逻辑：先查缓存，未命中则调 Tavily，结果存缓存。"""
    cached = get_cached(query, days)
    if cached is not None:
        results = cached
        from_cache = True
    else:
        try:
            results = client.search(
                query=query,
                max_results=max_results,
                search_depth="advanced",
                days=days,
            )
            set_cached(query, days, "advanced", results)
            from_cache = False
        except Exception as e:
            return f"搜索失败：{str(e)}"

    if not results or "results" not in results:
        return f"未找到关于'{query}'的相关新闻。"

    date_ctx = get_date_context()
    cache_note = "（缓存）" if from_cache else ""
    output_lines = [
        f"搜索时间：{date_ctx['today']}{cache_note}",
        f"搜索关键词：{query}",
        f"时间范围：{time_label}",
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


@tool
def search_stock_news(query: str, max_results: int = 5) -> str:
    """
    搜索股票相关新闻和公告。
    输入搜索关键词，返回最新的新闻摘要列表。
    适用于搜索个股新闻、行业动态、政策信息、机构评级等。
    """
    return _search_with_cache(query, max_results, days=7, time_label="最近7天")


@tool
def search_stock_news_today(query: str, max_results: int = 5) -> str:
    """
    搜索股票今日最新动态，只返回当天或最近24小时的新闻。
    用于获取盘中实时消息、当日公告、突发事件等极短期信息。
    """
    return _search_with_cache(query, max_results, days=1, time_label="最近24小时")
