# 股票研究 Multi-Agent 智能投研系统

[![Test](https://github.com/Box0528/stock-multi-agent-system/actions/workflows/test.yml/badge.svg)](https://github.com/Box0528/stock-multi-agent-system/actions/workflows/test.yml)

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
- **自包含数据管道**：baostock 下载脚本已收编进仓库（非外部依赖），分析前自动检测数据新鲜度并增量更新
- **四层 Memory**（ChromaDB）：预测追踪 / 板块轮动 / 风控历史 / Agent 行为教训
- **记忆按真实交易日归档**：而非系统运行时刻，避免行情数据滞后时记忆归属错位
- **Reflection 复盘引擎**：对比历史预测与实际走势，评估准确率，归因到具体 Agent
- **Agent 行为教训闭环**：复盘产生的教训自动注入下次分析的 Agent prompt

### 部署与安全
- **共享密钥鉴权**：前端访问码弹窗 + 后端 `X-API-Key` 校验，未配置时不影响本地开发
- **接口限流**（slowapi）：按 IP 限制高成本端点调用频率，防止额度被刷爆
- **CORS 环境变量化**：部署时无需改代码，配置一行环境变量即可
- **容器化**：Dockerfile + docker-compose.yml（数据/向量库目录用 volume 持久化）
- **依赖版本锁定**：`requirements-lock.txt` 保证构建可复现

### 质量保证
- **128 个自动化测试**，分层覆盖：纯函数解析逻辑（如报告字段提取）→ 假 LLM 的 Agent prompt/输出处理逻辑（零真实 API 消耗）→ FastAPI 接口集成测试
- **GitHub Actions CI**：push/PR 自动跑全量测试
- **LLM 重试**（指数退避）+ 工具调用降级
- **Pydantic Settings** 集中配置，消除魔法数字
- **搜索缓存**：同一查询当天只调一次 Tavily API
- **价格数据主备降级**：akshare → 本地 CSV 兜底

## 技术栈

| 组件 | 技术 |
|------|------|
| Agent 编排 | LangGraph 1.2+ (StateGraph) |
| LLM | DeepSeek (deepseek-chat) via langchain-openai |
| 向量记忆 | ChromaDB + sentence-transformers |
| 后端 | FastAPI + SSE + slowapi |
| 数据源 | baostock (A股日线，已收编进仓库) + Tavily (新闻搜索) + akshare (实时价格) |
| 前端 | 原生 HTML/CSS/JS（模块化拆分）+ lightweight-charts |
| 测试 | pytest |
| CI/部署 | GitHub Actions + Docker |

## 快速启动

```bash
# 1. 安装依赖（项目以 sys.path 方式运行，不是 pip 安装包，直接装依赖即可）
pip install -r requirements-lock.txt

# 2. 配置 .env
cp .env.example .env
# 必填：DEEPSEEK_API_KEY、TAVILY_API_KEY
# 可选：ACCESS_KEY（部署到公网前建议设置）、CORS_ORIGINS

# 3. 启动服务
uvicorn api.server:app --host 0.0.0.0 --port 8000

# 4. 访问
# 浏览器打开 http://localhost:8000
```

### 用 Docker 启动

```bash
docker compose up --build
```

> Dockerfile/docker-compose.yml 已提供（数据目录用 volume 持久化），尚未在生产环境实测验证，本地优先用上面的方式启动。

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
│   ├── vector_store.py  # 四层记忆存取（I/O）
│   └── extraction.py    # 报告字段提取（纯函数，独立可测）
├── tools/                # Agent 工具集
│   ├── stock_data.py    # 量化选股/技术指标/板块统计
│   ├── search.py        # 新闻搜索（带缓存）
│   ├── price_api.py     # 实时价格（主备降级）
│   └── data_pipeline.py # 数据管道（调度 data_downloader.py）
├── data_downloader.py    # baostock 下载脚本（已收编，未改动核心逻辑）
├── api/server.py         # FastAPI + SSE + 鉴权/限流中间件
├── frontend/              # 前端（模块化）
│   ├── index.html
│   ├── css/main.css
│   └── js/                # sse-client / agent-timer / report-render / chart-render / auth / app
├── config.py              # Pydantic Settings 集中配置
├── Dockerfile / docker-compose.yml
├── .github/workflows/test.yml  # CI
└── tests/                 # 128 个自动化测试
    ├── test_agents/        # 假LLM测试：7个agent的prompt构建+输出处理
    ├── test_memory/        # 纯函数测试：报告字段提取
    ├── test_api/           # FastAPI 接口集成测试（含鉴权）
    ├── test_core/
    └── test_tools/
```

## 测试

```bash
pytest tests/ -v
```

测试分三层，没有一层依赖真实 LLM/网络调用：
- **纯函数层**（`test_memory/`）：直接灌各种格式的报告文本，断言提取结果
- **Agent层**（`test_agents/`）：monkeypatch 掉 `get_llm`，验证 prompt 拼接内容和输出后处理逻辑，零 API 消耗
- **接口层**（`test_api/`）：`TestClient` 直接打 FastAPI 路由，验证鉴权/限流/参数校验
