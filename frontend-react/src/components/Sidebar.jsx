import { useState, useRef, useEffect } from 'react'
import { apiFetch } from '../utils/apiFetch'

export default function Sidebar({ onResearch, onScan, stats, disabled }) {
  const [code, setCode] = useState('')
  const [lookup, setLookup] = useState(null) // {name, industry} | null
  const [lookupErr, setLookupErr] = useState(false)
  const timerRef = useRef(null)

  useEffect(() => {
    clearTimeout(timerRef.current)
    setLookup(null)
    setLookupErr(false)
    if (code.length < 6) return
    timerRef.current = setTimeout(async () => {
      try {
        const res = await apiFetch(`/api/lookup/${code}`)
        if (res.status === 401) return
        const data = await res.json()
        if (data.found) { setLookup({ name: data.name, industry: data.industry }); setLookupErr(false) }
        else { setLookup(null); setLookupErr(true) }
      } catch {}
    }, 300)
  }, [code])

  function handleResearch() {
    if (!code.trim()) return
    onResearch(code.trim(), lookup?.name || code.trim())
  }

  return (
    <aside className="sidebar">
      <div className="sidebar-section">
        <div className="section-label">研究目标</div>
        <div className="input-field">
          <label className="field-label">STOCK CODE</label>
          <input
            className="stock-input"
            type="text"
            placeholder="输入股票代码，如 600226"
            maxLength={6}
            value={code}
            onChange={e => setCode(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleResearch()}
            disabled={disabled}
          />
        </div>
        {lookup && (
          <div className="lookup-preview">
            <span className="lookup-name">{lookup.name}</span>
            <span className="lookup-industry">{lookup.industry}</span>
          </div>
        )}
        {lookupErr && <div className="lookup-err">未找到该股票代码</div>}
        <button className="btn-primary" onClick={handleResearch} disabled={disabled}>
          <span>▶</span> 启动分析
        </button>
        <button className="btn-secondary" onClick={onScan} disabled={disabled}>
          <span>🔍</span> 今日主动扫描
        </button>
      </div>

      <div className="stats-grid">
        <div className="stat-item">
          <span className="stat-val">6</span>
          <span className="stat-key">AGENTS</span>
        </div>
        <div className="stat-item">
          <span className="stat-val">{stats.done}</span>
          <span className="stat-key">DONE</span>
        </div>
        <div className="stat-item">
          <span className="stat-val">{stats.elapsed}</span>
          <span className="stat-key">ELAPSED</span>
        </div>
        <div className="stat-item">
          <span className="stat-val">{stats.tools}</span>
          <span className="stat-key">TOOLS</span>
        </div>
      </div>
    </aside>
  )
}
