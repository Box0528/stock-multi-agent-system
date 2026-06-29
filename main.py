import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
from langchain_core.messages import HumanMessage
from graph.workflow import workflow


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

    initial_state = {
        "messages":         [HumanMessage(content=f"请分析【{stock_name}】")],
        "stock_name":       stock_name,
        "stock_code":       "",   # 命令行模式不强制传代码
        "industry":         industry,
        "real_industry":    real_industry,
        "task_plan":        "",
        "technical_report": "",
        "news_report":      "",
        "sector_report":    "",
        "risk_report":      "",
        "final_report":     "",
        "current_step":     "start",
        "memory_context":   "",
        "has_history":      False,
        "last_advice":      "",
    }

    final_state = workflow.invoke(initial_state)
    return final_state["final_report"]


if __name__ == "__main__":
    STOCK_NAME = "有研新材"
    INDUSTRY   = "半导体材料"
    report = run_research(STOCK_NAME, INDUSTRY)
    print("\n" + "="*60)
    print(report)