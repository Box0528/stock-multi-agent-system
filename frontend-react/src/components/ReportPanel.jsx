import { renderMd } from '../utils/renderMd'

const TABS = [
  { id: 'final',  label: '综合报告' },
  { id: 'tech',   label: '技术分析' },
  { id: 'news',   label: '新闻舆情' },
  { id: 'sector', label: '板块分析' },
  { id: 'risk',   label: '风控报告' },
]

function ReportBody({ content }) {
  if (content === null) {
    return (
      <div className="skeleton-wrap">
        <div className="skeleton-line" style={{ width: '60%' }} />
        <div className="skeleton-line" />
        <div className="skeleton-line" style={{ width: '80%' }} />
        <div className="skeleton-line" style={{ width: '40%' }} />
      </div>
    )
  }
  return <div className="report-body" dangerouslySetInnerHTML={{ __html: renderMd(content) }} />
}

export default function ReportPanel({ reports, activeTab, onTabChange, reflection }) {
  return (
    <div className="report-panel">
      <div className="tab-nav">
        {TABS.map(t => (
          <button
            key={t.id}
            className={`tab-btn ${activeTab === t.id ? 'active' : ''}`}
            onClick={() => onTabChange(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div className="tab-content">
        {TABS.map(t => (
          <div key={t.id} className={`tab-panel ${activeTab === t.id ? 'active' : ''}`}>
            <ReportBody content={reports[t.id === 'final' ? 'final' : t.id === 'tech' ? 'tech' : t.id === 'news' ? 'news' : t.id === 'sector' ? 'sector' : 'risk']} />
            {t.id === 'final' && reflection && (
              <div className="reflection-block">
                <div className="reflection-label">🔍 REFLECTION ENGINE · 复盘分析</div>
                <div className="report-body" dangerouslySetInnerHTML={{ __html: renderMd(reflection) }} />
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
