import AgentCard from './AgentCard'

const AGENTS = ['technical', 'news', 'sector', 'supervisor', 'risk', 'reflection']

const ADVICE_COLOR = {
  '买入': '#4ade80',
  '观望': '#facc15',
  '回避': '#f87171',
  '未知': '#94a3b8',
  '分析失败': '#f87171',
}

function StockRow({ stock }) {
  const { name, code, status, agents = {}, advice, rating } = stock

  if (status === 'running') {
    return (
      <div className="scan-stock-running">
        <div className="scan-stock-header">
          <span className="scan-stock-badge badge-run">分析中</span>
          <span className="scan-stock-name">{name}</span>
          <span className="scan-stock-code">{code}</span>
        </div>
        <div className="agents-grid">
          {AGENTS.map(id => (
            <AgentCard key={id} id={id} {...(agents[id] || { status: 'idle', logs: [], elapsed: '--' })} />
          ))}
        </div>
      </div>
    )
  }

  if (status === 'done') {
    const color = ADVICE_COLOR[advice] || ADVICE_COLOR['未知']
    return (
      <div className="scan-stock-done">
        <span className="scan-stock-badge badge-done">完成</span>
        <span className="scan-stock-name">{name}</span>
        <span className="scan-stock-code">{code}</span>
        <span className="scan-stock-advice" style={{ color }}>{advice || '未知'}</span>
        <span className="scan-stock-rating">{rating || ''}</span>
      </div>
    )
  }

  // waiting
  return (
    <div className="scan-stock-waiting">
      <span className="scan-stock-badge badge-idle">等待</span>
      <span className="scan-stock-name">{name}</span>
      <span className="scan-stock-code">{code}</span>
    </div>
  )
}

export default function ScanStage({ stocks = [], stageLabel }) {
  return (
    <div className="agent-stage">
      <div className="stage-header">
        <span className="stage-title">扫描进行中</span>
        <span className="stage-sub">{stageLabel}</span>
      </div>
      <div className="scan-stock-list">
        {stocks.map((s, i) => (
          <StockRow key={s.code || i} stock={s} />
        ))}
      </div>
    </div>
  )
}
