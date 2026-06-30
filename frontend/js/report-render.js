// ── 骨架屏占位（报告内容到达前显示）──────────────────────────
function skeletonHTML() {
  return '<div class="skeleton-block"><div class="skeleton-line"></div><div class="skeleton-line"></div>' +
    '<div class="skeleton-line"></div><div class="skeleton-line"></div></div>';
}

// ── Markdown 渲染 ────────────────────────────────────────────
// 表格必须在加粗/斜体之前处理，避免单元格里残留的星号被斜体正则跨行吞掉文字
function renderMd(text) {
  if (!text) return '<p style="color:var(--muted)">暂无内容</p>';
  let esc = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

  esc = esc.replace(/^## (.+)$/gm, '<h2>$1</h2>');
  esc = esc.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  esc = esc.replace(/^---$/gm, '<hr>');

  // 表格：逐块识别"表头行 + 分隔行 + 数据行"，分隔行（如 |---|---|）直接丢弃
  esc = esc.replace(/(^\|.+\|\s*$\n^\|[\s:|-]+\|\s*$\n(?:^\|.+\|\s*$\n?)+)/gm, block => {
    const lines = block.trim().split('\n');
    const rows = lines.filter((_, i) => i !== 1).map(line => {
      const cells = line.replace(/^\||\|$/g, '').split('|').map(c => c.trim());
      return cells;
    });
    const [headerCells, ...bodyRows] = rows;
    const thead = '<thead><tr>' + headerCells.map(c => `<th>${c}</th>`).join('') + '</tr></thead>';
    const tbody = '<tbody>' + bodyRows.map(r => '<tr>' + r.map(c => `<td>${c}</td>`).join('') + '</tr>').join('') + '</tbody>';
    return `<table>${thead}${tbody}</table>`;
  });

  esc = esc
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/^[-*] (.+)$/gm, '<li>$1</li>')
    .replace(/(<li>[\s\S]*?<\/li>\n?)+/g, m => `<ul>${m}</ul>`)
    .replace(/\n\n+/g, '</p><p>')
    .replace(/^(?!<[htupol])(.+)$/gm, '$1')
    .trim();

  return esc;
}

// ── 结构化字段解析（对后端格式做防御性容错：允许残留的*强调符号）──
function parseRating(text) {
  const stars = (text.match(/\*{0,2}综合评级\*{0,2}[：:]\s*(⭐+)/) || [])[1] || '';
  const advice = (text.match(/\*{0,2}操作建议\*{0,2}[：:]\s*(买入|观望|回避)/) || [])[1] || '';
  // 风险等级新格式"文字在前+emoji在后"（如"低 🟢"），同时兼容旧格式"emoji在前"
  const riskMatch = text.match(/\*{0,2}风险等级\*{0,2}[：:]\s*(低|中|高|极高)?\s*[🟢🟡🔴⛔]*\s*(低|中|高|极高)?/);
  const risk = (riskMatch && (riskMatch[1] || riskMatch[2])) || '';
  return { stars, advice, risk };
}

function renderRating(stars, advice, risk) {
  const card = document.getElementById('rating-card');
  card.style.display = 'flex';
  card.classList.add('fade-in');
  document.getElementById('rc-stars').textContent = stars || '-';
  document.getElementById('rc-time').textContent = new Date().toLocaleString('zh-CN', { hour12: false });

  const tag = document.getElementById('rc-advice');
  tag.textContent = advice || '-';
  tag.className = 'advice-badge ' +
    (advice === '买入' ? 'adv-buy' : advice === '观望' ? 'adv-watch' : advice === '回避' ? 'adv-avoid' : '');

  const riskLevel = risk.includes('极高') ? 90 : risk.includes('高') ? 75
    : risk.includes('中') ? 50 : risk.includes('低') ? 20 : 0;
  document.getElementById('rm-market').style.width = riskLevel + '%';
  document.getElementById('rm-liquidity').style.width = (riskLevel * 0.7) + '%';
  document.getElementById('rm-sentiment').style.width = (riskLevel * 0.85) + '%';
}
