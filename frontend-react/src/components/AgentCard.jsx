const AGENT_META = {
  technical:  { icon: '📊', name: 'Technical Analyst', sub: '均线 · 换手率 · 量价分析' },
  news:       { icon: '📰', name: 'News Analyst',      sub: '舆情 · 信息分级 · 政策' },
  sector:     { icon: '🏭', name: 'Sector Analyst',    sub: '板块强度 · 资金流向' },
  supervisor: { icon: '🎯', name: 'Supervisor',        sub: '基金经理 · 综合研判' },
  risk:       { icon: '🛡️', name: 'Risk Manager',      sub: '风控审核 · 仓位建议' },
  reflection: { icon: '🔍', name: 'Reflection Engine', sub: '复盘 · 偏差归因 · 行为修正' },
}

const STATUS_LABEL = { idle: 'IDLE', running: 'RUN', done: 'DONE' }
const STATUS_CLASS = { idle: 'badge-idle', running: 'badge-run', done: 'badge-done' }

export default function AgentCard({ id, status = 'idle', logs = [], elapsed = '--' }) {
  const meta = AGENT_META[id]
  return (
    <div className={`agent-card agent-${status}`}>
      <div className="agent-head">
        <div className={`agent-icon ${status === 'running' ? 'agent-icon-pulse' : ''}`}>
          {meta.icon}
        </div>
        <div className="agent-info">
          <div className="agent-name">{meta.name}</div>
          <div className="agent-sub">{meta.sub}</div>
        </div>
        <div className="agent-meta">
          <span className={`agent-badge ${STATUS_CLASS[status]}`}>
            {STATUS_LABEL[status] || 'IDLE'}
          </span>
          <span className="agent-elapsed">{elapsed}</span>
        </div>
      </div>
      {logs.length > 0 && (
        <div className="agent-logs">
          {logs.map((log, i) => (
            <div key={i} className={`log-item ${log.type}`}>{log.msg}</div>
          ))}
        </div>
      )}
    </div>
  )
}
