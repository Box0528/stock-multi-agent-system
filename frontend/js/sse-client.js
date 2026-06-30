// 通用 SSE 流解析：按 \n\n 分块，解析 event/data，逐条回调
async function consumeSSE(resp, onEvent) {
  const reader = resp.body.getReader();
  const dec = new TextDecoder();
  let buf = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const parts = buf.split('\n\n');
    buf = parts.pop();
    for (const part of parts) {
      const evtLine = part.split('\n').find(l => l.startsWith('event:'));
      const dataLine = part.split('\n').find(l => l.startsWith('data:'));
      if (!dataLine) continue;
      const type = evtLine ? evtLine.slice(6).trim() : 'message';
      let data;
      try {
        data = JSON.parse(dataLine.slice(5).trim());
      } catch (e) {
        if (type === 'report') {
          console.error('报告 JSON 解析失败:', e.message, dataLine.slice(5, 200));
        }
        continue;
      }
      onEvent(type, data);
    }
  }
}
