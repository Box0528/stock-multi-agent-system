const agentStart = {};
const agentTimers = {};
let globalStart = 0;
let globalTimer = null;
let toolCount = 0;
let doneCount = 0;
const AGENTS = ['technical', 'news', 'sector', 'supervisor', 'risk'];

function startAgentTimer(agent) {
  if (agentTimers[agent]) clearInterval(agentTimers[agent]);
  agentStart[agent] = Date.now();
  agentTimers[agent] = setInterval(() => {
    const s = ((Date.now() - agentStart[agent]) / 1000).toFixed(1);
    const el = document.getElementById(`at-${agent}`);
    if (el) el.textContent = `${s}s`;
  }, 100);
}

function stopAgentTimer(agent) {
  if (agentTimers[agent]) {
    clearInterval(agentTimers[agent]);
    agentTimers[agent] = null;
  }
  if (agentStart[agent]) {
    const s = ((Date.now() - agentStart[agent]) / 1000).toFixed(1);
    const el = document.getElementById(`at-${agent}`);
    if (el) el.textContent = `${s}s`;
  }
}

function startGlobalTimer() {
  globalStart = Date.now();
  globalTimer = setInterval(() => {
    const s = Math.floor((Date.now() - globalStart) / 1000);
    document.getElementById('st-elapsed').textContent = `${s}s`;
  }, 500);
}

function stopGlobalTimer() {
  clearInterval(globalTimer);
}

function stopAllTimers() {
  Object.keys(agentTimers).forEach(a => {
    if (agentTimers[a]) { clearInterval(agentTimers[a]); agentTimers[a] = null; }
  });
  stopGlobalTimer();
}

function setAgent(agent, status, msg) {
  const row = document.getElementById(`ar-${agent}`);
  const badge = document.getElementById(`as-${agent}`);
  const icon = document.getElementById(`ar-${agent}`)?.querySelector('.agent-icon');
  if (!row) return;

  const prevStatus = row.className.replace('agent-row', '').trim();
  row.className = `agent-row ${status}`;
  badge.textContent = status === 'running' ? 'RUN' : status === 'done' ? 'DONE' : 'IDLE';

  if (status !== prevStatus && icon) {
    icon.classList.remove('pop');
    void icon.offsetWidth; // 强制重排，让动画能重新触发
    icon.classList.add('pop');
  }

  if (status === 'running' && !agentTimers[agent]) startAgentTimer(agent);
  if (status === 'done') {
    stopAgentTimer(agent);
    doneCount++;
    document.getElementById('st-done').textContent = doneCount;
    updateProgressBar();
  }

  if (msg) appendLog(agent, msg, 'ok');
}

function updateProgressBar() {
  const fill = document.getElementById('progress-fill');
  if (!fill) return;
  const pct = AGENTS.length ? Math.min(100, Math.round((doneCount / AGENTS.length) * 100)) : 0;
  fill.style.width = pct + '%';
}

function appendLog(agent, msg, type = '') {
  const logs = document.getElementById(`al-${agent}`);
  if (!logs) return;
  const d = document.createElement('div');
  d.className = `log-item ${type}`;
  d.textContent = msg;
  logs.appendChild(d);
  logs.scrollTop = logs.scrollHeight;
}

function incTool() {
  toolCount++;
  document.getElementById('st-tools').textContent = toolCount;
}

function resetUI() {
  doneCount = 0; toolCount = 0;
  AGENTS.forEach(a => {
    const row = document.getElementById(`ar-${a}`);
    const badge = document.getElementById(`as-${a}`);
    const logs = document.getElementById(`al-${a}`);
    const timer = document.getElementById(`at-${a}`);
    row.className = 'agent-row';
    badge.textContent = 'IDLE';
    logs.innerHTML = '';
    timer.textContent = '--';
    clearInterval(agentTimers[a]);
  });
  document.getElementById('st-done').textContent = '0';
  document.getElementById('st-tools').textContent = '0';
  document.getElementById('st-elapsed').textContent = '0s';
  document.getElementById('st-total').textContent = AGENTS.length;
  document.getElementById('empty').style.display = 'flex';
  document.getElementById('agents-stage').style.display = 'none';
  document.getElementById('report-wrap').classList.remove('visible');
  document.getElementById('rating-card').style.display = 'none';
  const klineCard = document.getElementById('kline-card');
  klineCard.style.display = '';
  document.getElementById('kline-chart').innerHTML = '';
  const fill = document.getElementById('progress-fill');
  if (fill) fill.style.width = '0%';
  const stageSub = document.getElementById('stage-sub');
  if (stageSub) stageSub.textContent = '准备中...';
}
