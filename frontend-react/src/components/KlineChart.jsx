import { useEffect, useRef } from 'react'
import { apiFetch } from '../utils/apiFetch'

export default function KlineChart({ stockCode }) {
  const containerRef = useRef(null)

  useEffect(() => {
    if (!stockCode || !containerRef.current) return
    const container = containerRef.current
    container.innerHTML = ''

    const LC = window.LightweightCharts
    if (!LC) {
      container.innerHTML = '<div class="chart-empty">图表库加载中...</div>'
      return
    }

    let chart = null

    apiFetch(`/api/kline/${stockCode}`)
      .then(r => r.ok ? r.json() : Promise.reject('无K线数据'))
      .then(data => {
        const candles = data.candles || []
        if (!candles.length) { container.innerHTML = '<div class="chart-empty">暂无K线数据</div>'; return }
        const volumeUnit = data.volume_unit || '手'

        chart = LC.createChart(container, {
          width: container.clientWidth,
          height: 260,
          layout: { background: { color: 'transparent' }, textColor: '#9ca3af', fontFamily: 'system-ui', fontSize: 11 },
          grid: { vertLines: { color: '#f3f4f6' }, horzLines: { color: '#f3f4f6' } },
          rightPriceScale: { borderColor: '#e5e7eb' },
          timeScale: { borderColor: '#e5e7eb' },
          crosshair: { mode: LC.CrosshairMode.Normal },
          // Prevent chart from stealing page scroll events
          handleScroll: { mouseWheel: false, pressedMouseMove: true },
          handleScale: { mouseWheel: false, pinch: false },
        })

        const candleSeries = chart.addCandlestickSeries({
          upColor: '#e0473f', downColor: '#15a566',
          borderUpColor: '#e0473f', borderDownColor: '#15a566',
          wickUpColor: '#e0473f', wickDownColor: '#15a566',
        })
        candleSeries.setData(candles.map(c => ({ time: c.time, open: c.open, high: c.high, low: c.low, close: c.close })))
        chart.priceScale('right').applyOptions({ scaleMargins: { top: 0.05, bottom: 0.28 } })

        const volumeSeries = chart.addHistogramSeries({
          priceFormat: { type: 'volume' },
          priceScaleId: '',
          scaleMargins: { top: 0.80, bottom: 0 },
        })
        volumeSeries.setData(candles.map(c => ({
          time: c.time, value: c.volume,
          color: c.close >= c.open ? 'rgba(224,71,63,.4)' : 'rgba(21,165,102,.4)',
        })))

        chart.timeScale().fitContent()

        // Tooltip
        const byTime = Object.fromEntries(candles.map(c => [c.time, c]))
        let tip = document.createElement('div')
        tip.className = 'kline-tooltip'
        container.style.position = 'relative'
        container.appendChild(tip)

        chart.subscribeCrosshairMove(param => {
          if (!param.point || !param.time || param.point.x < 0 || param.point.y < 0) { tip.style.display = 'none'; return }
          const c = byTime[param.time]
          if (!c) { tip.style.display = 'none'; return }
          const dir = c.close >= c.open ? '#e0473f' : '#15a566'
          tip.style.display = 'block'
          tip.innerHTML = `<div class="kt-date">${c.time}</div>` +
            `<div class="kt-row">开 <span>${c.open.toFixed(2)}</span> 收 <span style="color:${dir}">${c.close.toFixed(2)}</span></div>` +
            `<div class="kt-row">高 <span>${c.high.toFixed(2)}</span> 低 <span>${c.low.toFixed(2)}</span></div>` +
            `<div class="kt-row">量 <span>${c.volume.toLocaleString('zh-CN')} ${volumeUnit}</span></div>`
          const x = Math.min(Math.max(param.point.x + 12, 0), container.clientWidth - 150)
          tip.style.left = x + 'px'
          tip.style.top = '8px'
        })

        const onResize = () => chart && chart.applyOptions({ width: container.clientWidth })
        window.addEventListener('resize', onResize)
        return () => window.removeEventListener('resize', onResize)
      })
      .catch(() => { if (container) container.innerHTML = '<div class="chart-empty">暂无K线数据</div>' })

    return () => { if (chart) chart.remove() }
  }, [stockCode])

  return (
    <div className="chart-card">
      <div className="chart-title">K线 / 成交量</div>
      <div ref={containerRef} className="chart-container" />
    </div>
  )
}
