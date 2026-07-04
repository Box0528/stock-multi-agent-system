export function parseRating(text) {
  const stars = (text.match(/\*{0,2}综合评级\*{0,2}[：:]\s*(⭐+)/) || [])[1] || ''
  const advice = (text.match(/\*{0,2}操作建议\*{0,2}[：:]\s*(买入|观望|回避)/) || [])[1] || ''
  const riskMatch = text.match(/\*{0,2}风险等级\*{0,2}[：:]\s*(低|中|高|极高)?\s*[🟢🟡🔴⛔]*\s*(低|中|高|极高)?/)
  const risk = (riskMatch && (riskMatch[1] || riskMatch[2])) || ''
  return { stars, advice, risk }
}
