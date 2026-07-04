export default function EmptyState() {
  return (
    <div className="empty-state">
      <div className="empty-cards">
        <div className="empty-card">
          <div className="ec-icon">📊</div>
          <div className="ec-label">技术分析</div>
        </div>
        <div className="empty-card">
          <div className="ec-icon">📰</div>
          <div className="ec-label">新闻舆情</div>
        </div>
        <div className="empty-card">
          <div className="ec-icon">🏭</div>
          <div className="ec-label">板块研究</div>
        </div>
      </div>
      <div className="empty-title">输入股票，启动六大 Agent 协同分析</div>
      <div className="empty-sub">技术 · 新闻 · 板块 · 基金经理 · 风控 · 复盘</div>
    </div>
  )
}
