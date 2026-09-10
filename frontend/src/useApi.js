import { useState, useCallback } from 'react'

const API = 'http://localhost:8000'

export function useApi() {
  const get = useCallback(async (path) => {
    const res = await fetch(`${API}${path}`)
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
    return res.json()
  }, [])

  const post = useCallback(async (path, body) => {
    const res = await fetch(`${API}${path}`, {
      method: 'POST',
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined,
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || `${res.status} ${res.statusText}`)
    }
    if (res.status === 204) return null
    return res.json()
  }, [])

  const del = useCallback(async (path) => {
    const res = await fetch(`${API}${path}`, { method: 'DELETE' })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || `${res.status} ${res.statusText}`)
    }
    return null
  }, [])

  return { get, post, del }
}
