import { useState, useEffect } from 'react'

export default function Header({ systemOnline }) {
  const [time, setTime] = useState('')

  useEffect(() => {
    const tick = () => setTime(new Date().toLocaleTimeString('zh-CN', { hour12: false }))
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [])

  return (
    <header className="app-header">
      <div className="header-logo">
        <span className="logo-mark">■</span>
        <span className="logo-text">StockAgent</span>
        <span className="logo-sub">/ Multi-Agent 投研系统</span>
      </div>
      <div className="header-mid">
        <span className={`status-pill ${systemOnline ? 'online' : 'offline'}`}>
          <span className="pill-dot" />
          {systemOnline ? '系统在线' : '系统离线'}
        </span>
      </div>
      <div className="header-right">
        <span className="header-clock">{time}</span>
      </div>
    </header>
  )
}
