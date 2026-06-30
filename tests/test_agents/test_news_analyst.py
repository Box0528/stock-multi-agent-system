import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from datetime import datetime
import agents.news_analyst as news_module
from agents.news_analyst import run_news_analyst
from tests.test_agents.conftest import system_content, human_content


def test_today_date_in_system_prompt(make_fake_llm):
    fake = make_fake_llm(news_module, "## 新闻舆情分析报告\n...")
    run_news_analyst("亨通股份")
    this_year = str(datetime.now().year)
    assert this_year in system_content(fake)


def test_sentiment_scoring_forbidden(make_fake_llm):
    fake = make_fake_llm(news_module, "...")
    run_news_analyst("亨通股份")
    assert "禁止做情感评分" in system_content(fake)


def test_industry_injected(make_fake_llm):
    fake = make_fake_llm(news_module, "...")
    run_news_analyst("亨通股份", industry="D44电力、热力生产和供应业")
    assert "D44电力、热力生产和供应业" in human_content(fake)


def test_price_context_injected(make_fake_llm):
    fake = make_fake_llm(news_module, "...")
    run_news_analyst("亨通股份", price_context="最新收盘价：18.20元，涨跌幅+2.3%")
    assert "最新收盘价：18.20元" in human_content(fake)


def test_search_keywords_from_planner_injected(make_fake_llm):
    fake = make_fake_llm(news_module, "...")
    run_news_analyst("亨通股份", search_keywords=["亨通股份 业绩", "电力设备 政策"])
    assert "消息面指令" in human_content(fake)
    assert "亨通股份 业绩" in human_content(fake)


def test_lessons_appended(make_fake_llm):
    fake = make_fake_llm(news_module, "...")
    run_news_analyst("亨通股份", lessons="上次把过期新闻当成新信号")
    assert "历史教训" in system_content(fake)
    assert "上次把过期新闻当成新信号" in system_content(fake)


def test_self_eval_parsed_and_stripped(make_fake_llm):
    content = "## 新闻舆情分析报告\n消息面方向：中性\n\n---自评估---\n- 置信度：60%"
    make_fake_llm(news_module, content)
    result = run_news_analyst("亨通股份")
    assert result.confidence == 0.6
    assert "自评估" not in result.report


def test_search_call_recorded_on_tool_use(make_fake_llm_sequence, monkeypatch):
    class FakeSearchTool:
        def invoke(self, args):
            return "[A级] 亨通股份签订海外大单（2026-06-30，财联社）"

    monkeypatch.setattr(news_module, "TOOL_MAP", {"search_stock_news_today": FakeSearchTool()})

    search_call_count = []

    class FakeTracker:
        def record_llm_call(self, **kw): pass
        def record_tool_call(self): pass
        def record_search_call(self): search_call_count.append(1)

    tool_call = {"name": "search_stock_news_today", "args": {"query": "亨通股份"}, "id": "call_1"}
    make_fake_llm_sequence(news_module, [
        ("", [tool_call]),
        ("## 新闻舆情分析报告\n消息面方向：利多", []),
    ])

    result = run_news_analyst("亨通股份", tracker=FakeTracker())
    assert search_call_count == [1]
    assert "消息面方向：利多" in result.report
