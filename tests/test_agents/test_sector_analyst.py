import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from datetime import datetime
import agents.sector_analyst as sector_module
from agents.sector_analyst import run_sector_analyst
from tests.test_agents.conftest import system_content, human_content


def test_today_and_year_in_system_prompt(make_fake_llm):
    fake = make_fake_llm(sector_module, "## 板块分析报告\n...")
    run_sector_analyst("D44电力、热力生产和供应业")
    this_year = str(datetime.now().year)
    assert this_year in system_content(fake)


def test_industry_name_in_query(make_fake_llm):
    fake = make_fake_llm(sector_module, "...")
    run_sector_analyst("D44电力、热力生产和供应业")
    assert "D44电力、热力生产和供应业" in human_content(fake)


def test_stock_name_focus_injected_when_provided(make_fake_llm):
    fake = make_fake_llm(sector_module, "...")
    run_sector_analyst("D44电力、热力生产和供应业", stock_name="亨通股份")
    assert "亨通股份" in human_content(fake)


def test_stock_name_omitted_when_not_provided(make_fake_llm):
    fake = make_fake_llm(sector_module, "...")
    run_sector_analyst("D44电力、热力生产和供应业")
    assert "重点关注" not in human_content(fake)


def test_lessons_appended(make_fake_llm):
    fake = make_fake_llm(sector_module, "...")
    run_sector_analyst("D44电力、热力生产和供应业", lessons="上次只看强度评分忽略了轮动阶段")
    assert "历史教训" in system_content(fake)
    assert "上次只看强度评分忽略了轮动阶段" in system_content(fake)


def test_self_eval_parsed_and_stripped(make_fake_llm):
    content = "## 板块分析报告\n板块强度评分：75/100\n\n---自评估---\n- 置信度：70%"
    make_fake_llm(sector_module, content)
    result = run_sector_analyst("D44电力、热力生产和供应业")
    assert result.confidence == 0.7
    assert "自评估" not in result.report


def test_max_rounds_fallback(make_fake_llm_sequence):
    """连续12轮都返回 tool_calls，应该触发兜底返回，而不是无限循环。"""
    tool_call = {"name": "analyze_sector", "args": {"industry_name": "x"}, "id": "call_1"}
    fake = make_fake_llm_sequence(sector_module, [("", [tool_call])] * 12)
    # TOOL_MAP 里没mock，真实 analyze_sector 会被调用；为了不依赖真实数据，
    # 这里只验证轮次耗尽后的兜底文案，不关心工具实际返回什么。
    import agents.sector_analyst as m

    class NoopTool:
        def invoke(self, args):
            return "no data"
    m_tool_map_backup = m.TOOL_MAP
    m.TOOL_MAP = {"analyze_sector": NoopTool()}
    try:
        result = run_sector_analyst("D44电力、热力生产和供应业")
    finally:
        m.TOOL_MAP = m_tool_map_backup

    assert "分析超过最大轮次" in result.report
    assert fake.invoke_count == 12
