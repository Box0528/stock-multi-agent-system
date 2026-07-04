export function getAccessKey() {
  return localStorage.getItem('access_key') || ''
}

export function setAccessKey(key) {
  localStorage.setItem('access_key', key)
}

export function clearAccessKey() {
  localStorage.removeItem('access_key')
}

export async function apiFetch(url, opts = {}) {
  const headers = { ...opts.headers, 'X-API-Key': getAccessKey() }
  return fetch(url, { ...opts, headers })
}
