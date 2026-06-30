let _klineChart = null;
let _klineCandleSeries = null;
let _klineVolumeSeries = null;

function _ensureTooltip(container) {
  let tip = container.querySelector('.kline-tooltip');
  if (!tip) {
    tip = document.createElement('div');
    tip.className = 'kline-tooltip';
    container.style.position = 'relative';
    container.appendChild(tip);
  }
  return tip;
}

async function renderKlineChart(stockCode) {
  const container = document.getElementById('kline-chart');
  if (!container) return;
  container.innerHTML = '';

  if (typeof LightweightCharts === 'undefined') {
    container.innerHTML = '<div class="chart-empty">图表库加载失败</div>';
    return;
  }

  let data;
  try {
    const resp = await apiFetch(`/api/kline/${stockCode}`);
    if (!resp.ok) throw new Error('无K线数据');
    data = await resp.json();
  } catch (e) {
    container.innerHTML = '<div class="chart-empty">暂无K线数据</div>';
    return;
  }

  const candles = data.candles || [];
  if (candles.length === 0) {
    container.innerHTML = '<div class="chart-empty">暂无K线数据</div>';
    return;
  }
  const volumeUnit = data.volume_unit || '手';

  const chart = LightweightCharts.createChart(container, {
    width: container.clientWidth,
    height: 260,
    layout: { background: { color: 'transparent' }, textColor: '#8e8e93', fontFamily: '-apple-system,sans-serif', fontSize: 11 },
    grid: { vertLines: { color: '#eeeef1' }, horzLines: { color: '#eeeef1' } },
    rightPriceScale: { borderColor: '#e3e3e7' },
    timeScale: { borderColor: '#e3e3e7' },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
  });

  const candleSeries = chart.addCandlestickSeries({
    upColor: '#e0473f', downColor: '#15a566',
    borderUpColor: '#e0473f', borderDownColor: '#15a566',
    wickUpColor: '#e0473f', wickDownColor: '#15a566',
  });
  candleSeries.setData(candles.map(c => ({ time: c.time, open: c.open, high: c.high, low: c.low, close: c.close })));

  const volumeSeries = chart.addHistogramSeries({
    priceFormat: { type: 'volume' },
    priceScaleId: '',
    scaleMargins: { top: 0.82, bottom: 0 },
  });
  volumeSeries.setData(candles.map(c => ({
    time: c.time, value: c.volume,
    color: c.close >= c.open ? 'rgba(224,71,63,.45)' : 'rgba(21,165,102,.45)',
  })));

  chart.timeScale().fitContent();
  _klineChart = chart;
  _klineCandleSeries = candleSeries;
  _klineVolumeSeries = volumeSeries;

  const byTime = {};
  candles.forEach(c => { byTime[c.time] = c; });
  const tooltip = _ensureTooltip(container);

  chart.subscribeCrosshairMove(param => {
    if (!param.point || !param.time || param.point.x < 0 || param.point.y < 0) {
      tooltip.style.display = 'none';
      return;
    }
    const c = byTime[param.time];
    if (!c) { tooltip.style.display = 'none'; return; }
    const dir = c.close >= c.open ? '#e0473f' : '#15a566';
    tooltip.style.display = 'block';
    tooltip.innerHTML =
      `<div class="kt-date">${c.time}</div>` +
      `<div class="kt-row">开 <span>${c.open.toFixed(2)}</span> 收 <span style="color:${dir}">${c.close.toFixed(2)}</span></div>` +
      `<div class="kt-row">高 <span>${c.high.toFixed(2)}</span> 低 <span>${c.low.toFixed(2)}</span></div>` +
      `<div class="kt-row">量 <span>${c.volume.toLocaleString('zh-CN')} ${volumeUnit}</span></div>`;

    const x = Math.min(Math.max(param.point.x + 12, 0), container.clientWidth - 150);
    tooltip.style.left = x + 'px';
    tooltip.style.top = '8px';
  });

  window.addEventListener('resize', () => {
    if (_klineChart) _klineChart.applyOptions({ width: container.clientWidth });
  });
}
