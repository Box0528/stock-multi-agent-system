export async function consumeSSE(resp, onEvent) {
  const reader = resp.body.getReader()
  const dec = new TextDecoder()
  let buf = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += dec.decode(value, { stream: true })
    const parts = buf.split('\n\n')
    buf = parts.pop()
    for (const part of parts) {
      const evtLine = part.split('\n').find(l => l.startsWith('event:'))
      const dataLine = part.split('\n').find(l => l.startsWith('data:'))
      if (!dataLine) continue
      const type = evtLine ? evtLine.slice(6).trim() : 'message'
      let data
      try { data = JSON.parse(dataLine.slice(5).trim()) } catch { continue }
      onEvent(type, data)
    }
  }
}
