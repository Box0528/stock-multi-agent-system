import { useState, useRef, useCallback } from 'react'
import { useAuth } from './hooks/useAuth'
import { useHistory } from './hooks/useHistory'
import { apiFetch } from './utils/apiFetch'
import { consumeSSE } from './utils/consumeSSE'
import { parseRating } from './utils/parseRating'
import AccessGate from './components/AccessGate'
import Header from './components/Header'
import Sidebar from './components/Sidebar'
import HistorySidebar from './components/HistorySidebar'
import EmptyState from './components/EmptyState'
import AgentStage from './components/AgentStage'
import RatingCard from './components/RatingCard'
import KlineChart from './components/KlineChart'
import ReportPanel from './components/ReportPanel'
import StatusBar from './components/StatusBar'

const AGENTS = ['technical', 'news', 'sector', 'supervisor', 'risk', 'reflection']

function initAgents() {
  return Object.fromEntries(AGENTS.map(a => [a, { status: 'idle', logs: [], elapsed: '--' }]))
}

export default function App() {
  const { hasKey, submit: submitKey } = useAuth()
  const { history, addHistory, removeHistory } = useHistory()

  const [phase, setPhase] = useState('idle')
  const [currentCode, setCurrentCode] = useState('')
  const [currentName, setCurrentName] = useState('')
  const [stageLabel, setStageLabel] = useState('')
  const [agents, setAgents] = useState(initAgents())
  const [stats, setStats] = useState({ done: 0, elapsed: '0s', tools: 0 })
  const [reports, setReports] = useState({ final: null, tech: null, news: null, sector: null, risk: null })
  const [rating, setRating] = useState(null)
  const [ratingTime, setRatingTime] = useState('')
  const [activeTab, setActiveTab] = useState('final')
  const [statusState, setStatusState] = useState('idle')
  const [statusText, setStatusText] = useState('就绪 — 输入股票代码开始分析')
  const [totalCost, setTotalCost] = useState('')
  const [reflection, setReflection] = useState(null)
  const [showKline, setShowKline] = useState(true)
  const [activeHistoryId, setActiveHistoryId] = useState(null)

  const agentStarts = useRef({})
  const agentIntervals = useRef({})
  const globalStart = useRef(0)
  const globalInterval = useRef(null)
  const finalReportRef = useRef('')
  const riskReportRef = useRef('')
  const allReportsRef = useRef({})
  // Refs to avoid stale closure in SSE handlers (React state updates are batched/async)
  const currentCodeRef = useRef('')
  const currentNameRef = useRef('')

  // ── Timers ───────────────────────────────────────────────
  function startGlobalTimer() {
    globalStart.current = Date.now()
    globalInterval.current = setInterval(() => {
      const s = Math.floor((Date.now() - globalStart.current) / 1000)
      setStats(prev => ({ ...prev, elapsed: `${s}s` }))
    }, 500)
  }

  function stopGlobalTimer() { clearInterval(globalInterval.current) }

  function startAgentTimer(agent) {
    clearInterval(agentIntervals.current[agent])
    agentStarts.current[agent] = Date.now()
    agentIntervals.current[agent] = setInterval(() => {
      const s = ((Date.now() - agentStarts.current[agent]) / 1000).toFixed(1)
      setAgents(prev => ({ ...prev, [agent]: { ...prev[agent], elapsed: `${s}s` } }))
    }, 100)
  }

  function stopAgentTimer(agent) {
    clearInterval(agentIntervals.current[agent])
    agentIntervals.current[agent] = null
    const s = ((Date.now() - agentStarts.current[agent]) / 1000).toFixed(1)
    setAgents(prev => ({ ...prev, [agent]: { ...prev[agent], elapsed: `${s}s` } }))
  }

  function stopAllTimers() {
    AGENTS.forEach(a => { clearInterval(agentIntervals.current[a]); agentIntervals.current[a] = null })
    stopGlobalTimer()
  }

  // ── State helpers ─────────────────────────────────────────
  function resetAll() {
    setPhase('idle')
    setAgents(initAgents())
    setStats({ done: 0, elapsed: '0s', tools: 0 })
    setReports({ final: null, tech: null, news: null, sector: null, risk: null })
    setRating(null)
    setTotalCost('')
    setReflection(null)
    setShowKline(true)
    setActiveTab('final')
    setActiveHistoryId(null)
    finalReportRef.current = ''
    riskReportRef.current = ''
    allReportsRef.current = {}
  }

  function setAgentStatus(agent, status, msg) {
    setAgents(prev => {
      const logs = msg ? [...prev[agent].logs, { msg, type: 'ok' }] : prev[agent].logs
      return { ...prev, [agent]: { ...prev[agent], status, logs } }
    })
    if (status === 'running' && !agentIntervals.current[agent]) startAgentTimer(agent)
    if (status === 'done') {
      stopAgentTimer(agent)
      setStats(prev => ({ ...prev, done: prev.done + 1 }))
    }
  }

  function appendLog(agent, msg, type = 'tool') {
    setAgents(prev => ({
      ...prev,
      [agent]: { ...prev[agent], logs: [...prev[agent].logs, { msg, type }] }
    }))
  }

  // ── 保存到历史 ────────────────────────────────────────────
  function saveToHistory(code, name, rpts, ref, rat) {
    const { stars, advice, risk } = rat
    const entry = {
      id: Date.now(),
      code,
      name,
      advice,
      stars,
      risk,
      timestamp: new Date().toISOString(),
      reports: rpts,
      reflection: ref,
    }
    addHistory(entry)
    setActiveHistoryId(entry.id)
    return entry.id
  }

  // ── 加载历史条目 ──────────────────────────────────────────
  function loadHistory(item) {
    setPhase('report')
    setCurrentCode(item.code)
    setCurrentName(item.name || item.code)
    setReports(item.reports || {})
    setReflection(item.reflection || null)
    setActiveTab('final')
    setShowKline(true)
    setActiveHistoryId(item.id)
    const r = item
    setRating(r.advice || r.stars ? { stars: r.stars, advice: r.advice, risk: r.risk } : null)
    setRatingTime(item.timestamp ? new Date(item.timestamp).toLocaleString('zh-CN', { hour12: false }) : '')
    setStatusState('done')
    setStatusText(`已加载历史记录：${item.name || item.code}(${item.code})`)
    setTotalCost('')
  }

  // ── SSE event handler（research）────────────────────────
  const handleEvent = useCallback((type, data) => {
    if (type === 'progress') {
      const { agent, status, message } = data
      setAgentStatus(agent, status, message)
      if (message) setStatusText(message)

    } else if (type === 'tool_call') {
      appendLog(data.agent, data.message, 'tool')
      setStats(prev => ({ ...prev, tools: prev.tools + 1 }))

    } else if (type === 'stock_info') {
      const sName = data.stock_name || ''
      setCurrentName(sName)
      currentNameRef.current = sName
      setStatusText(`正在分析 ${data.stock_name}(${data.stock_code})...`)

    } else if (type === 'report_meta') {
      setPhase('report')
      setReports({ final: null, tech: null, news: null, sector: null, risk: null })
      allReportsRef.current = {}

    } else if (type === 'report_final_report') {
      finalReportRef.current = data.content
      allReportsRef.current.final = data.content
      setReports(prev => ({ ...prev, final: data.content }))

    } else if (type === 'report_technical_report') {
      allReportsRef.current.tech = data.content
      setReports(prev => ({ ...prev, tech: data.content }))

    } else if (type === 'report_news_report') {
      allReportsRef.current.news = data.content
      setReports(prev => ({ ...prev, news: data.content }))

    } else if (type === 'report_sector_report') {
      allReportsRef.current.sector = data.content
      setReports(prev => ({ ...prev, sector: data.content }))

    } else if (type === 'report_risk_report') {
      riskReportRef.current = data.content
      allReportsRef.current.risk = data.content
      setReports(prev => ({ ...prev, risk: data.content }))

    } else if (type === 'report_done') {
      stopGlobalTimer()
      const rat = parseRating(finalReportRef.current + riskReportRef.current)
      setRating(rat)
      const t = new Date().toLocaleString('zh-CN', { hour12: false })
      setRatingTime(t)

    } else if (type === 'reflection') {
      allReportsRef.current.reflection = data.content
      setReflection(data.content)
      setStatusText('复盘完成 — 预测' + (data.was_correct ? '正确 ✓' : '存在偏差，已记录'))

    } else if (type === 'cost_summary') {
      const c = data
      setTotalCost(`LLM ${c.llm_calls}次 · Token ${c.total_tokens} · 搜索 ${c.search_api_calls}次 · 工具 ${c.tool_calls}次`)

    } else if (type === 'error') {
      stopGlobalTimer()
      setStatusState('error')
      setStatusText('分析出错：' + data.message)

    } else if (type === 'done') {
      stopAllTimers()
      setStatusState('done')
      setStatusText('分析完成 ✓')
      // Use refs to avoid stale closure — state may not have updated yet
      const rat = parseRating(finalReportRef.current + riskReportRef.current)
      saveToHistory(
        currentCodeRef.current,
        currentNameRef.current,
        { ...allReportsRef.current },
        allReportsRef.current.reflection || null,
        rat,
      )
    }
  }, [])

  // ── SSE event handler（scan）────────────────────────────
  const handleScanEvent = useCallback((type, data) => {
    if (type === 'progress') {
      const { agent, status, message } = data
      setAgentStatus(agent, status, message)
      if (message) setStatusText(message)

    } else if (type === 'tool_call') {
      appendLog(data.agent, data.message, 'tool')
      setStats(prev => ({ ...prev, tools: prev.tools + 1 }))

    } else if (type === 'scan_result') {
      setPhase('report')
      setShowKline(false)
      const overview = data.market_overview || '无数据'
      const join = key => {
        try {
          const reps = JSON.parse(data.analysis_reports || '[]')
          return reps.map(r =>
            `### ${r.name}（${r.code}）— ${r.industry}\n精选理由：${r.reason}\n\n${r[key] || '暂无'}\n\n---`
          ).join('\n\n')
        } catch { return '' }
      }
      const rpts = {
        final: overview,
        tech: '## 各股票技术分析汇总\n\n' + join('technical_report'),
        news: '## 各股票新闻舆情汇总\n\n' + join('news_report'),
        sector: '## 各股票板块分析汇总\n\n' + join('sector_report'),
        risk: '## 各股票风控评估汇总\n\n' + join('risk_report'),
      }
      setReports(rpts)
      stopGlobalTimer()
      const total = ((Date.now() - globalStart.current) / 1000).toFixed(1)
      setTotalCost(`总耗时 ${total}s`)

    } else if (type === 'cost_summary') {
      const c = data
      setTotalCost(prev => (prev ? prev + ' | ' : '') + `LLM ${c.llm_calls}次 · Token ${c.total_tokens}`)

    } else if (type === 'error') {
      stopGlobalTimer()
      setStatusState('error')
      setStatusText('扫描出错：' + data.message)

    } else if (type === 'done') {
      stopAllTimers()
      setStatusState('done')
      setStatusText('扫描完成 ✓')
    }
  }, [])

  // ── Actions ───────────────────────────────────────────────
  async function startResearch(code, displayName) {
    resetAll()
    setCurrentCode(code)
    setCurrentName(displayName)
    // Sync refs immediately so SSE handler always has fresh values
    currentCodeRef.current = code
    currentNameRef.current = displayName
    setStageLabel(`${displayName}(${code})`)
    setPhase('running')
    setStatusState('running')
    setStatusText(`正在分析 ${displayName}(${code})...`)
    startGlobalTimer()
    try {
      const resp = await apiFetch('/api/research', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ stock_code: code }),
      })
      if (resp.status === 401) { setStatusState('error'); setStatusText('访问码错误'); return }
      await consumeSSE(resp, handleEvent)
    } catch (e) {
      setStatusState('error')
      setStatusText('连接失败：' + e.message)
    }
    stopAllTimers()
  }

  async function startScan() {
    resetAll()
    setStageLabel('全市场筛选中...')
    setPhase('running')
    setStatusState('running')
    setStatusText('正在执行今日主动扫描...')
    startGlobalTimer()
    try {
      const resp = await apiFetch('/api/scan', { method: 'POST' })
      if (resp.status === 401) { setStatusState('error'); setStatusText('访问码错误'); return }
      await consumeSSE(resp, handleScanEvent)
    } catch (e) {
      setStatusState('error')
      setStatusText('扫描失败：' + e.message)
    }
    stopAllTimers()
  }

  const running = statusState === 'running'

  if (!hasKey) return <AccessGate onSubmit={submitKey} />

  return (
    <div className="app-layout">
      <Header systemOnline />
      <div className="progress-rail">
        <div className="progress-fill" style={{ width: `${Math.min(100, Math.round((stats.done / 6) * 100))}%` }} />
      </div>
      <div className="workspace">
        <HistorySidebar
          history={history}
          onLoad={loadHistory}
          onRemove={removeHistory}
          activeId={activeHistoryId}
        />
        <Sidebar
          onResearch={startResearch}
          onScan={startScan}
          stats={stats}
          disabled={running}
        />
        <main className="main-panel">
          {phase === 'idle' && <EmptyState />}
          {phase === 'running' && <AgentStage agents={agents} stageLabel={stageLabel} />}
          {phase === 'report' && (
            <>
              <RatingCard rating={rating} time={ratingTime} />
              {showKline && <KlineChart stockCode={currentCode} />}
              <ReportPanel
                reports={reports}
                activeTab={activeTab}
                onTabChange={setActiveTab}
                reflection={reflection}
              />
            </>
          )}
          <StatusBar statusState={statusState} statusText={statusText} totalCost={totalCost} />
        </main>
      </div>
    </div>
  )
}
