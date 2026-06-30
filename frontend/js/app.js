// ── 时钟 ──────────────────────────────────────────────────────
setInterval(() => {
  document.getElementById('clock').textContent =
    new Date().toLocaleTimeString('zh-CN', { hour12: false });
}, 1000);

// ── Tab 切换（交叉淡入淡出）─────────────────────────────────
function switchTab(name, btn) {
  const newPanel = document.getElementById(`tp-${name}`);
  const oldPanel = document.querySelector('.tab-panel.active');
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  if (oldPanel === newPanel) return;

  if (oldPanel) {
    oldPanel.classList.add('tab-leaving');
    setTimeout(() => oldPanel.classList.remove('active', 'tab-leaving'), 150);
  }
  newPanel.classList.add('active', 'tab-entering');
  requestAnimationFrame(() => newPanel.classList.remove('tab-entering'));
}

// ── 侧栏开关（窄屏）──────────────────────────────────────────
function toggleSidebar() {
  document.querySelector('.panel-left').classList.toggle('open');
}

// ── 实时查询股票名称 ──────────────────────────────────────────
let lookupTimer = null;
function onCodeInput(val) {
  clearTimeout(lookupTimer);
  const preview = document.getElementById('stock-preview');
  const err = document.getElementById('code-error');
  preview.style.display = 'none';
  err.style.display = 'none';
  if (val.length < 6) return;
  lookupTimer = setTimeout(async () => {
    try {
      const res = await apiFetch(`/api/lookup/${val}`);
      const data = await res.json();
      if (data.found) {
        document.getElementById('preview-name').textContent = data.name;
        document.getElementById('preview-industry').textContent = data.industry;
        preview.style.display = 'block';
        err.style.display = 'none';
      } else {
        preview.style.display = 'none';
        err.style.display = 'block';
      }
    } catch (e) {}
  }, 300);
}

// ── 模式二：指定分析 ──────────────────────────────────────────
let _currentCode = '';

function startResearch() {
  const code = document.getElementById('inp-code').value.trim();
  if (!code) { alert('请输入股票代码'); return; }
  _currentCode = code;

  const previewName = document.getElementById('preview-name').textContent;
  const displayName = previewName || code;

  resetUI();
  document.getElementById('btn-run').disabled = true;
  document.getElementById('sdot').className = 'status-dot running';
  document.getElementById('stext').textContent = `正在分析 ${displayName}(${code})...`;
  startGlobalTimer();
  fetchSSE(code);
}

async function fetchSSE(code) {
  try {
    const resp = await apiFetch('/api/research', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ stock_code: code }),
    });
    await consumeSSE(resp, handleEvent);
  } catch (e) {
    document.getElementById('sdot').className = 'status-dot error';
    document.getElementById('stext').textContent = '连接失败：' + e.message;
    document.getElementById('btn-run').disabled = false;
  }
  stopAllTimers();
}

function fillReport(elId, content) {
  const el = document.getElementById(elId);
  el.innerHTML = renderMd(content);
  el.classList.remove('fade-in');
  void el.offsetWidth;
  el.classList.add('fade-in');
}

function handleEvent(type, data) {
  if (type === 'progress') {
    const { agent, status, message } = data;
    setAgent(agent, status, message);
    document.getElementById('stext').textContent = message || '';

  } else if (type === 'tool_call') {
    appendLog(data.agent, data.message, 'tool');
    incTool();

  } else if (type === 'stock_info') {
    document.getElementById('stext').textContent = `正在分析 ${data.stock_name}(${data.stock_code})...`;

  } else if (type === 'report_meta') {
    document.getElementById('empty').style.display = 'none';
    const wrap = document.getElementById('report-wrap');
    wrap.classList.add('visible', 'fade-in');
    ['rb-final', 'rb-tech', 'rb-news', 'rb-sector', 'rb-risk', 'rb-plan'].forEach(id => {
      document.getElementById(id).innerHTML = skeletonHTML();
    });
    renderKlineChart(_currentCode);
    const chartCard = document.getElementById('kline-card');
    chartCard.classList.add('fade-in');

  } else if (type === 'report_final_report') {
    fillReport('rb-final', data.content);
    window._finalReport = data.content;

  } else if (type === 'report_technical_report') {
    fillReport('rb-tech', data.content);

  } else if (type === 'report_news_report') {
    fillReport('rb-news', data.content);

  } else if (type === 'report_sector_report') {
    fillReport('rb-sector', data.content);

  } else if (type === 'report_risk_report') {
    fillReport('rb-risk', data.content);
    window._riskReport = data.content;

  } else if (type === 'report_task_plan') {
    fillReport('rb-plan', data.content);

  } else if (type === 'report_done') {
    stopGlobalTimer();
    const fr = window._finalReport || '';
    const rr = window._riskReport || '';
    const { stars, advice, risk } = parseRating(fr + rr);
    renderRating(stars, advice, risk);
    const total = ((Date.now() - globalStart) / 1000).toFixed(1);
    document.getElementById('stotal').textContent = `总耗时 ${total}s`;

  } else if (type === 'error') {
    stopGlobalTimer();
    document.getElementById('sdot').className = 'status-dot error';
    document.getElementById('stext').textContent = '分析出错：' + data.message;
    document.getElementById('btn-run').disabled = false;

  } else if (type === 'reflection') {
    const finalEl = document.getElementById('rb-final');
    const divider = '<hr><div style="background:rgba(124,92,240,.06);border:1px solid rgba(124,92,240,.18);border-radius:var(--r-lg);padding:16px;margin-top:16px">' +
      '<div style="color:#7c5cf0;font-size:11px;font-weight:600;letter-spacing:.04em;margin-bottom:10px">🔍 REFLECTION ENGINE · 复盘分析</div>' +
      renderMd(data.content) + '</div>';
    finalEl.innerHTML += divider;
    const correct = data.was_correct;
    document.getElementById('stext').textContent = '复盘完成 — 预测' + (correct ? '正确 ✓' : '存在偏差，已记录');

  } else if (type === 'cost_summary') {
    const c = data;
    const costText = `LLM ${c.llm_calls}次 · Token ${c.total_tokens} · 搜索 ${c.search_api_calls}次 · 工具 ${c.tool_calls}次`;
    document.getElementById('stotal').textContent += ` | ${costText}`;

  } else if (type === 'done') {
    stopAllTimers();
    document.getElementById('sdot').className = 'status-dot done';
    document.getElementById('stext').textContent = '分析完成 ✓';
    document.getElementById('btn-run').disabled = false;
  }
}

// ── 模式一：主动扫描 ──────────────────────────────────────────
async function startScan() {
  resetUI();
  document.getElementById('btn-run').disabled = true;
  document.getElementById('btn-scan').disabled = true;
  document.getElementById('sdot').className = 'status-dot running';
  document.getElementById('stext').textContent = '正在执行今日主动扫描...';
  startGlobalTimer();

  try {
    const resp = await apiFetch('/api/scan', { method: 'POST' });
    await consumeSSE(resp, handleScanEvent);
  } catch (e) {
    document.getElementById('sdot').className = 'status-dot error';
    document.getElementById('stext').textContent = '扫描失败：' + e.message;
  }
  stopAllTimers();
  document.getElementById('btn-run').disabled = false;
  document.getElementById('btn-scan').disabled = false;
}

function handleScanEvent(type, data) {
  if (type === 'progress') {
    const { agent, status, message } = data;
    setAgent(agent, status, message);
    document.getElementById('stext').textContent = message || '';
  } else if (type === 'tool_call') {
    appendLog(data.agent, data.message, 'tool');
    incTool();
  } else if (type === 'scan_result') {
    document.getElementById('empty').style.display = 'none';
    document.getElementById('report-wrap').classList.add('visible', 'fade-in');
    document.getElementById('kline-card').style.display = 'none';
    const overview = data.market_overview || '无数据';
    fillReport('rb-final', overview);

    try {
      const reports = JSON.parse(data.analysis_reports || '[]');
      if (reports.length > 0) {
        let techHtml = '<h2>各股票技术分析汇总</h2>';
        let newsHtml = '<h2>各股票新闻舆情汇总</h2>';
        let sectorHtml = '<h2>各股票板块分析汇总</h2>';
        let riskHtml = '<h2>各股票风控评估汇总</h2>';
        for (const r of reports) {
          const header = `<h3>${r.name}（${r.code}）— ${r.industry}</h3><p style="color:var(--muted)">精选理由：${r.reason}</p>`;
          techHtml += header + renderMd(r.technical_report || '暂无') + '<hr>';
          newsHtml += header + renderMd(r.news_report || '暂无') + '<hr>';
          sectorHtml += header + renderMd(r.sector_report || '暂无') + '<hr>';
          riskHtml += header + renderMd(r.risk_report || '暂无') + '<hr>';
        }
        document.getElementById('rb-tech').innerHTML = techHtml;
        document.getElementById('rb-news').innerHTML = newsHtml;
        document.getElementById('rb-sector').innerHTML = sectorHtml;
        document.getElementById('rb-risk').innerHTML = riskHtml;
      }
    } catch (e) { console.error('解析扫描报告失败', e); }

    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    document.querySelector('.tab-btn').classList.add('active');
    document.getElementById('rb-final').parentElement.classList.add('active');
    const ratingCard = document.querySelector('.rating-card');
    if (ratingCard) ratingCard.style.display = 'none';
    stopGlobalTimer();
    const total = ((Date.now() - globalStart) / 1000).toFixed(1);
    document.getElementById('stotal').textContent = `总耗时 ${total}s`;
  } else if (type === 'cost_summary') {
    const c = data;
    const costText = `LLM ${c.llm_calls}次 · Token ${c.total_tokens} · 搜索 ${c.search_api_calls}次`;
    document.getElementById('stotal').textContent += ` | ${costText}`;
  } else if (type === 'error') {
    stopGlobalTimer();
    document.getElementById('sdot').className = 'status-dot error';
    document.getElementById('stext').textContent = '扫描出错：' + data.message;
  } else if (type === 'done') {
    stopAllTimers();
    document.getElementById('sdot').className = 'status-dot done';
    document.getElementById('stext').textContent = '扫描完成 ✓';
  }
}
