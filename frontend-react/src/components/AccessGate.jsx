import { useState } from 'react'

export default function AccessGate({ onSubmit }) {
  const [val, setVal] = useState('')
  const [err, setErr] = useState(false)

  function submit() {
    if (!val.trim()) { setErr(true); return }
    const ok = onSubmit(val.trim())
    if (!ok) setErr(true)
  }

  return (
    <div className="gate-overlay">
      <div className="gate-card">
        <div className="gate-title">请输入访问码</div>
        <div className="gate-sub">本系统需要访问码才能调用分析接口</div>
        <input
          type="password"
          className="gate-input"
          placeholder="访问码"
          value={val}
          onChange={e => { setVal(e.target.value); setErr(false) }}
          onKeyDown={e => e.key === 'Enter' && submit()}
          autoFocus
        />
        {err && <div className="gate-err">访问码不能为空</div>}
        <button className="gate-btn" onClick={submit}>确认</button>
      </div>
    </div>
  )
}
