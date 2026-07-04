import { useState } from 'react'
import { getAccessKey, setAccessKey, clearAccessKey } from '../utils/apiFetch'

export function useAuth() {
  const [hasKey, setHasKey] = useState(() => Boolean(getAccessKey()))

  function submit(key) {
    if (!key.trim()) return false
    setAccessKey(key.trim())
    setHasKey(true)
    return true
  }

  function reset() {
    clearAccessKey()
    setHasKey(false)
  }

  return { hasKey, submit, reset }
}
