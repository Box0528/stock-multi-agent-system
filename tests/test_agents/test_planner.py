import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from datetime import datetime
import agents.planner as planner_module
from agents.planner import run_planner
from tests.test_agents.conftest import system_content, human_content


def test_today_date_injected_into_query(make_fake_llm):
    """回归测试：Planner 之前从不注入当前日期，导致 LLM 凭训练数据猜年份（出过2024硬编码的bug）。"""
    fake = make_fake_llm(planner_module, "## 研究任务计划 · 亨通股份\n...")
    run_planner("亨通股份")
    this_year = str(datetime.now().year)
    assert "当前日期" in human_content(fake)
    assert this_year in human_content(fake)


def test_system_prompt_forbids_stale_year(make_fake_llm):
    fake = make_fake_llm(planner_module, "...")
    run_planner("亨通股份")
    assert "时间基准" in system_content(fake)
    assert "禁止使用与当前年份不符的年份" in system_content(fake)


def test_industry_injected_when_provided(make_fake_llm):
    fake = make_fake_llm(planner_module, "...")
    run_planner("亨通股份", industry="D44电力、热力生产和供应业")
    assert "系统确认的行业分类" in human_content(fake)
    assert "D44电力、热力生产和供应业" in human_content(fake)


def test_industry_omitted_when_not_provided(make_fake_llm):
    fake = make_fake_llm(planner_module, "...")
    run_planner("亨通股份")
    assert "系统确认的行业分类" not in human_content(fake)


def test_concept_info_injected(make_fake_llm):
    fake = make_fake_llm(planner_module, "...")
    run_planner("亨通股份", concept_info="所属概念：CPO概念、PCB概念")
    assert "CPO概念" in human_content(fake)


def test_returns_llm_content_unchanged(make_fake_llm):
    make_fake_llm(planner_module, "## 研究任务计划 · 亨通股份\n具体内容")
    result = run_planner("亨通股份")
    assert result == "## 研究任务计划 · 亨通股份\n具体内容"


def test_records_cost_when_tracker_provided(make_fake_llm):
    make_fake_llm(planner_module, "...")
    calls = []

    class FakeTracker:
        def record_llm_call(self, input_tokens, output_tokens):
            calls.append((input_tokens, output_tokens))

    run_planner("亨通股份", tracker=FakeTracker())
    assert calls == [(10, 20)]
