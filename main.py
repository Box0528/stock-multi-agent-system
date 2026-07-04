import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import logging
import pandas as pd
from langchain_core.messages import HumanMessage
from graph.workflow import workflow
from core.event_bus import ConsoleEventBus
from core.cost_tracker import CostTracker

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")


def lookup_industry(stock_name: str) -> str:
    try:
        meta_file = os.path.join(os.path.dirname(__file__), "meta", "stock_meta.csv")
        meta_df = pd.read_csv(meta_file)
        match = meta_df[meta_df["name"] == stock_name]
        if not match.empty:
            return match.iloc[0]["industry_name"]
    except Exception as e:
        print(f"[Warning] 行业查询失败：{e}")
    return ""


def run_research(stock_name: str, industry: str = "") -> str:
    real_industry = lookup_industry(stock_name)
    print(f"\n{'='*60}")
    print(f"  股票研究 Multi-Agent 启动")
    print(f"  目标股票：{stock_name}")
    print(f"  真实行业：{real_industry or '未找到'}")
    print(f"{'='*60}\n")

    bus = ConsoleEventBus()
    tracker = CostTracker()

    initial_state = {
        "messages":         [HumanMessage(content=f"请分析【{stock_name}】")],
        "stock_name":       stock_name,
        "stock_code":       "",
        "industry":         industry,
        "real_industry":    real_industry,
        "technical_report": "",
        "news_report":      "",
        "sector_report":    "",
        "risk_report":      "",
        "final_report":     "",
        "current_step":     "start",
        "memory_context":   "",
        "has_history":      False,
        "last_advice":      "",
        "agent_lessons":    "",
        "technical_confidence": 0.7,
        "news_confidence":      0.7,
        "sector_confidence":    0.7,
        "reasoning_traces":     "",
    }

    config = {"configurable": {"event_bus": bus, "cost_tracker": tracker}}
    final_state = workflow.invoke(initial_state, config=config)

    # 打印成本统计
    cost = tracker.snapshot()
    print(f"\n{'='*60}")
    print(f"  成本统计")
    print(f"  LLM 调用：{cost.llm_calls} 次")
    print(f"  Token 消耗：{cost.total_tokens}（输入 {cost.total_input_tokens} / 输出 {cost.total_output_tokens}）")
    print(f"  搜索 API：{cost.search_api_calls} 次")
    print(f"  工具调用：{cost.tool_calls} 次")
    print(f"{'='*60}\n")

    return final_state["final_report"]


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="股票研究 Multi-Agent CLI")
    parser.add_argument("stock", help="股票名称，如：有研新材")
    parser.add_argument("--industry", default="", help="行业（可选，自动从 meta 查询）")
    args = parser.parse_args()

    report = run_research(args.stock, args.industry)
    print("\n" + "="*60)
    print(report)
