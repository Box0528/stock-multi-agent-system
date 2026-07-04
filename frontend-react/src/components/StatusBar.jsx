export default function StatusBar({ statusState, statusText, totalCost }) {
  return (
    <div className="status-bar">
      <span className={`sdot sdot-${statusState}`} />
      <span className="status-text">{statusText}</span>
      {totalCost && <span className="status-cost">{totalCost}</span>}
    </div>
  )
}
