import { useState } from 'react'
import { formatTime } from '../hooks/useHistory'

const ADVICE_COLOR = {
  '买入': { bg: '#d1fae5', color: '#065f46' },
  '观望': { bg: '#fef3c7', color: '#92400e' },
  '回避': { bg: '#fee2e2', color: '#991b1b' },
}

export default function HistorySidebar({ history, onLoad, onRemove, activeId }) {
  const [collapsed, setCollapsed] = useState(false)

  return (
    <div className={`hist-sidebar ${collapsed ? 'hist-collapsed' : ''}`}>

      {/* 折叠时只显示竖排标题 + 展开按钮 */}
      {collapsed ? (
        <div className="hist-collapsed-inner">
          <button className="hist-toggle" onClick={() => setCollapsed(false)} title="展开历史记录">
            ▶
          </button>
          <span className="hist-collapsed-label">历史</span>
        </div>
      ) : (
        <>
          <div className="hist-header">
            <span className="hist-title">历史分析</span>
            <span className="hist-count">{history.length}</span>
            <button className="hist-toggle" onClick={() => setCollapsed(true)} title="折叠">
              ◀
            </button>
          </div>

          <div className="hist-list">
            {history.length === 0 && (
              <div className="hist-empty">暂无历史记录<br />完成分析后自动保存</div>
            )}
            {history.map(item => {
              const adv = ADVICE_COLOR[item.advice] || { bg: '#f3f4f6', color: '#6b7280' }
              const isActive = item.id === activeId
              return (
                <div
                  key={item.id}
                  className={`hist-item ${isActive ? 'hist-item-active' : ''}`}
                  onClick={() => onLoad(item)}
                >
                  <div className="hist-item-top">
                    <span className="hist-code">{item.code}</span>
                    {item.advice && (
                      <span className="hist-badge" style={{ background: adv.bg, color: adv.color }}>
                        {item.advice}
                      </span>
                    )}
                  </div>
                  <div className="hist-name">{item.name || '—'}</div>
                  <div className="hist-time">{formatTime(item.timestamp)}</div>
                  <button
                    className="hist-del"
                    onClick={e => { e.stopPropagation(); onRemove(item.id) }}
                    title="删除"
                  >×</button>
                </div>
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}
