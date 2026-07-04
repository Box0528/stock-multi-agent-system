const ADVICE_CLASS = { '买入': 'adv-buy', '观望': 'adv-watch', '回避': 'adv-avoid' }

function riskPct(risk) {
  if (risk.includes('极高')) return 90
  if (risk.includes('高')) return 75
  if (risk.includes('中')) return 50
  if (risk.includes('低')) return 20
  return 0
}

export default function RatingCard({ rating, time }) {
  if (!rating) return null
  const { stars, advice, risk } = rating
  const pct = riskPct(risk)

  return (
    <div className="rating-card">
      <div className="rc-item">
        <span className="rc-key">综合评级</span>
        <span className="rc-val">{stars || '-'}</span>
      </div>
      <div className="rc-divider" />
      <div className="rc-item">
        <span className="rc-key">操作建议</span>
        <span className={`advice-badge ${ADVICE_CLASS[advice] || ''}`}>{advice || '-'}</span>
      </div>
      <div className="rc-divider" />
      <div className="rc-item">
        <span className="rc-key">风险维度</span>
        <div className="risk-meters">
          <div className="risk-meter">
            <div className="rm-bar"><div className="rm-fill rm-market" style={{ width: pct + '%' }} /></div>
            <span className="rm-label">市场</span>
          </div>
          <div className="risk-meter">
            <div className="rm-bar"><div className="rm-fill rm-liquidity" style={{ width: (pct * 0.7) + '%' }} /></div>
            <span className="rm-label">流动</span>
          </div>
          <div className="risk-meter">
            <div className="rm-bar"><div className="rm-fill rm-sentiment" style={{ width: (pct * 0.85) + '%' }} /></div>
            <span className="rm-label">情绪</span>
          </div>
        </div>
      </div>
      {time && <span className="rc-time">{time}</span>}
    </div>
  )
}
