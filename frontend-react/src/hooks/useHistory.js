import { useState } from 'react'

const KEY = 'stock_analysis_history'
const MAX = 30

function load() {
  try { return JSON.parse(localStorage.getItem(KEY) || '[]') } catch { return [] }
}

function save(list) {
  localStorage.setItem(KEY, JSON.stringify(list))
}

export function useHistory() {
  const [history, setHistory] = useState(load)

  function addHistory(entry) {
    // entry: { id, code, name, advice, stars, risk, timestamp, reports, reflection }
    setHistory(prev => {
      const next = [entry, ...prev.filter(h => h.id !== entry.id)].slice(0, MAX)
      save(next)
      return next
    })
  }

  function removeHistory(id) {
    setHistory(prev => {
      const next = prev.filter(h => h.id !== id)
      save(next)
      return next
    })
  }

  function clearHistory() {
    setHistory([])
    save([])
  }

  return { history, addHistory, removeHistory, clearHistory }
}

// 格式化时间为可读字符串
export function formatTime(isoStr) {
  if (!isoStr) return ''
  const d = new Date(isoStr)
  const now = new Date()
  const diff = now - d
  const oneDay = 86400000

  const hm = d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })

  if (diff < oneDay && d.getDate() === now.getDate()) return `今天 ${hm}`
  if (diff < 2 * oneDay) return `昨天 ${hm}`
  if (diff < 7 * oneDay) {
    const days = ['日', '一', '二', '三', '四', '五', '六']
    return `周${days[d.getDay()]} ${hm}`
  }
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${m}/${day} ${hm}`
}
