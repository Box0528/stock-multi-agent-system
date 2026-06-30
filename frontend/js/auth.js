// 访问码网关：服务端 ACCESS_KEY 未配置时，缺少/错误的 key 也会被放行（后端不校验），
// 这里只负责让前端体验一致——首次打开要求输入一次，之后自动带上。
function getAccessKey() {
  return localStorage.getItem('access_key') || '';
}

function setAccessKey(key) {
  localStorage.setItem('access_key', key);
}

function ensureAccessKey() {
  if (getAccessKey()) return;
  showAccessGate();
}

function showAccessGate() {
  if (document.getElementById('access-gate')) return;
  const overlay = document.createElement('div');
  overlay.id = 'access-gate';
  overlay.className = 'access-gate';
  overlay.innerHTML = `
    <div class="access-gate-card">
      <div class="access-gate-title">请输入访问码</div>
      <div class="access-gate-sub">本系统需要访问码才能调用分析接口</div>
      <input id="access-gate-input" type="password" placeholder="访问码" autocomplete="off">
      <button id="access-gate-btn" class="btn-run">确认</button>
      <div class="access-gate-err" id="access-gate-err" style="display:none">访问码不能为空</div>
    </div>`;
  document.body.appendChild(overlay);

  const input = document.getElementById('access-gate-input');
  const submit = () => {
    const val = input.value.trim();
    if (!val) {
      document.getElementById('access-gate-err').style.display = 'block';
      return;
    }
    setAccessKey(val);
    overlay.remove();
  };
  document.getElementById('access-gate-btn').onclick = submit;
  input.addEventListener('keydown', e => { if (e.key === 'Enter') submit(); });
  input.focus();
}

// 统一 fetch 封装：自动带上 X-API-Key，401 时弹回访问码输入框让用户重试
async function apiFetch(url, opts = {}) {
  const headers = Object.assign({}, opts.headers || {}, { 'X-API-Key': getAccessKey() });
  const resp = await fetch(url, Object.assign({}, opts, { headers }));
  if (resp.status === 401) {
    localStorage.removeItem('access_key');
    showAccessGate();
  }
  return resp;
}

ensureAccessKey();
