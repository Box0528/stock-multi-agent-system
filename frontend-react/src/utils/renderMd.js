export function renderMd(text) {
  if (!text) return '<p style="color:#9ca3af">暂无内容</p>'
  let s = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

  s = s.replace(/^## (.+)$/gm, '<h2>$1</h2>')
  s = s.replace(/^### (.+)$/gm, '<h3>$1</h3>')
  s = s.replace(/^---$/gm, '<hr>')

  s = s.replace(/(^\|.+\|\s*$\n^\|[\s:|-]+\|\s*$\n(?:^\|.+\|\s*$\n?)+)/gm, block => {
    const lines = block.trim().split('\n')
    const rows = lines.filter((_, i) => i !== 1).map(line =>
      line.replace(/^\||\|$/g, '').split('|').map(c => c.trim())
    )
    const [headerCells, ...bodyRows] = rows
    const thead = '<thead><tr>' + headerCells.map(c => `<th>${c}</th>`).join('') + '</tr></thead>'
    const tbody = '<tbody>' + bodyRows.map(r => '<tr>' + r.map(c => `<td>${c}</td>`).join('') + '</tr>').join('') + '</tbody>'
    return `<table>${thead}${tbody}</table>`
  })

  s = s
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/^[-*] (.+)$/gm, '<li>$1</li>')
    .replace(/(<li>[\s\S]*?<\/li>\n?)+/g, m => `<ul>${m}</ul>`)
    .replace(/\n\n+/g, '</p><p>')
    .trim()

  return s
}

export function skeletonHTML() {
  return `<div class="skeleton-wrap">
    <div class="skeleton-line" style="width:60%"></div>
    <div class="skeleton-line"></div>
    <div class="skeleton-line" style="width:80%"></div>
    <div class="skeleton-line" style="width:40%"></div>
  </div>`
}
