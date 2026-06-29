import os

base = r"D:\normal software\PYproject\Agent工程"

structure = [
    "main.py",
    "config.py",
    "agents/__init__.py",
    "agents/technical_analyst.py",
    "agents/news_analyst.py",
    "agents/sector_analyst.py",
    "agents/risk_manager.py",
    "agents/planner.py",
    "agents/supervisor.py",
    "tools/__init__.py",
    "tools/stock_data.py",
    "tools/search.py",
    "memory/__init__.py",
    "memory/vector_store.py",
    "graph/__init__.py",
    "graph/workflow.py",
]

for path in structure:
    full_path = os.path.join(base, path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    if not os.path.exists(full_path):
        open(full_path, "w").close()
        print(f"创建: {path}")
    else:
        print(f"已存在: {path}")

print("\n目录结构创建完成")