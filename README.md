# 股票研究 Multi-Agent 智能投研系统

基于 LangGraph 编排的多智能体协作投研系统，模拟基金公司的投研团队工作模式。

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│  模式一：主动扫描                 模式二：指定分析             │
│  POST /api/scan                  POST /api/research         │
├─────────────┬───────────────────────────────────────────────┤
│             │                                               │
│  数据管道    │  data_refresh (baostock 增量更新)             │
│             │                                               │
├─────────────┼───────────────────────────────────────────────┤
│             │                                               │
│  选股层     │  量化选股 → LLM 精选 Top 3-5                    │
│  (仅模式一)  │  (纯本地计算，零搜索成本)                       │
│             │                                               │
├─────────────┼───────────────────────────────────────────────┤
│             │         多智能体分析引擎                        │
│             │                                               │
│  Memory     │  ┌──────────┐                                 │
│  加载       │  │ Planner  │ 任务规划                         │
│             │  └────┬─────┘                                 │
│             │       │                                       │
│  分析师     │  ┌────┴────┬────────────┬────────────┐        │
│  (真并行)   │  │Technical│   News     │  Sector    │        │
│             │  │Analyst  │  Analyst   │  Analyst   │        │
│             │  └────┬────┴─────┬──────┴─────┬──────┘        │
│             │       └──────────┼────────────┘               │
│  汇总       │           ┌─────┴──────┐                      │
│             │           │ Supervisor │ 基金经理               │
│             │           └─────┬──────┘                      │
│             │           ┌─────┴──────┐                      │
│  风控       │           │Risk Manager│ 风控审核               │
│             │           └─────┬──────┘                      │
│             │                 │                              │
│  记忆       │  Memory Save + Reflection (异步复盘)           │
│             │                                               │
└─────────────┴───────────────────────────────────────────────┘
```

## 两种工作模式

**模式一 — 主动研究（项目核心）**：系统自主扫描全市场，量化选股筛出候选池，LLM 精选 Top 3-5 只，然后对每只股票执行完整多智能体深度分析，输出今日投研排名报告。

**模式二 — 指定分析**：用户输入股票代码，系统对该股票执行完整的多智能体分析，输出研究报告。

两种模式形成"发现机会 → 深度研究"的完整投研闭环。

## 技术亮点

### 工程架构
- **LangGraph StateGraph** 编排 7 个 Agent 节点，显式状态流转
- **ThreadPoolExecutor 真并行**：3 个分析师并发执行，耗时取最慢的一个（非串行累加）
- **结构化事件总线**（EventBus）替代 monkey-patch print，每个请求独立实例，解决并发竞态
- **SSE 流式推送**：实时展示每个 Agent 的执行状态、工具调用、推理过程
- **成本追踪器**（CostTracker）：线程安全，统计 LLM 调用/Token/搜索/工具消耗

### 数据与记忆
- **自动数据管道**：分析前检测数据新鲜度，自动调用 baostock 增量更新
- **三层 Memory**（ChromaDB）：预测追踪 / 板块轮动 / 风控历史
- **Reflection 复盘引擎**：对比历史预测与实际走势，评估准确率
- **Agent 行为教训**：复盘产生的教训自动注入下次分析的 Agent prompt

### 韧性与质量
- **LLM 重试**（指数退避）+ 工具调用降级
- **Pydantic Settings** 集中配置，消除魔法数字
- **搜索缓存**：同一查询当天只调一次 Tavily API
- **39 个自动化测试**（pytest），覆盖核心模块
- **价格数据主备降级**：akshare → 本地 CSV 兜底

## 技术栈

| 组件 | 技术 |
|------|------|
| Agent 编排 | LangGraph 1.2+ (StateGraph) |
| LLM | DeepSeek (deepseek-chat) via langchain-openai |
| 向量记忆 | ChromaDB + sentence-transformers |
| 后端 | FastAPI + SSE |
| 数据源 | baostock (A股日线) + Tavily (新闻搜索) + akshare (实时价格) |
| 前端 | 原生 HTML/CSS/JS 单文件，投研终端风格 |
| 测试 | pytest |

## 快速启动

```bash
# 1. 安装依赖
pip install -e .

# 2. 配置 .env
cp .env.example .env
# 填入 DEEPSEEK_API_KEY 和 TAVILY_API_KEY

# 3. 启动服务
uvicorn api.server:app --host 0.0.0.0 --port 8000

# 4. 访问
# 浏览器打开 http://localhost:8000
```

## 目录结构

```
├── agents/              # 7 个 Agent 实现
│   ├── planner.py       # 任务规划
│   ├── technical_analyst.py  # 技术分析（工具：选股/个股指标）
│   ├── news_analyst.py  # 新闻舆情（工具：Tavily 搜索）
│   ├── sector_analyst.py # 板块分析（工具：板块统计/搜索）
│   ├── supervisor.py    # 基金经理（汇总+置信度加权）
│   ├── risk_manager.py  # 风控审核
│   └── reflection.py    # 复盘引擎
├── core/                # 核心基础设施
│   ├── event_bus.py     # 结构化事件总线
│   ├── cost_tracker.py  # 成本追踪器
│   ├── cognitive.py     # 认知协议（推理链/自评估）
│   ├── resilience.py    # 重试机制
│   └── cache.py         # 搜索缓存
├── graph/               # LangGraph 工作流
│   ├── workflow.py      # 模式二：指定分析
│   └── scan_workflow.py # 模式一：主动扫描
├── memory/              # ChromaDB 向量记忆
│   └── vector_store.py  # 四层记忆 + Agent 教训
├── tools/               # Agent 工具集
│   ├── stock_data.py    # 量化选股/技术指标/板块统计
│   ├── search.py        # 新闻搜索（带缓存）
│   ├── price_api.py     # 实时价格（主备降级）
│   └── data_pipeline.py # 数据管道（baostock 增量更新）
├── api/server.py        # FastAPI + SSE
├── frontend/index.html  # 投研终端前端
├── config.py            # Pydantic Settings 集中配置
└── tests/               # 39 个自动化测试
```

## 测试

```bash
pytest tests/ -v
```
