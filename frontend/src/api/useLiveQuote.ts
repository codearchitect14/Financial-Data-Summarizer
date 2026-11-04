import { useEffect, useState } from 'react'
import { fetchQuote } from './client'
import type { Quote } from './types'

export const QUOTE_REFRESH_MS = 30_000

/**
 * Keeps a quote current while it's on screen. This calls Yahoo through the backend and
 * uses no LLM quota. It stops while the tab is hidden, to avoid being rate-limited.
 *
 * If an update fails, or only a saved quote is available, the last live price stays on
 * screen and `paused` is set, so an old price is never presented as live.
 */
export function useLiveQuote(ticker: string, initial: Quote | null) {
  const [quote, setQuote] = useState(initial)
  const [paused, setPaused] = useState(false)

  useEffect(() => {
    const controller = new AbortController()

    async function refresh() {
      if (document.hidden) return
      try {
        const latest = await fetchQuote(ticker, controller.signal)
        if (latest.is_saved) {
          setPaused(true)
          return
        }
        setQuote(latest)
        setPaused(false)
      } catch {
        if (!controller.signal.aborted) setPaused(true)
      }
    }

    const timer = window.setInterval(refresh, QUOTE_REFRESH_MS)
    document.addEventListener('visibilitychange', refresh)
    return () => {
      controller.abort()
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', refresh)
    }
  }, [ticker])

  return { quote, paused }
}
