import type { Briefing, BriefingFailure, ChatMessage, ChatResponse, ProgressEvent, Quote } from './types'

export interface BriefingHandlers {
  onProgress: (event: ProgressEvent) => void
  onResult: (briefing: Briefing) => void
  onFailed: (failure: BriefingFailure) => void
}

/**
 * Streams one briefing, and returns a function that stops listening.
 *
 * It must close on every final event. EventSource reconnects by itself when a stream
 * ends, which would generate the briefing again and pay for it twice.
 */
export function streamBriefing(
  ticker: string,
  useBackupLlm: boolean,
  handlers: BriefingHandlers,
): () => void {
  const query = useBackupLlm ? '?force_failover=true' : ''
  const source = new EventSource(`/api/briefings/${encodeURIComponent(ticker)}/stream${query}`)

  source.addEventListener('progress', (event) => {
    handlers.onProgress(JSON.parse(event.data))
  })
  source.addEventListener('result', (event) => {
    source.close()
    handlers.onResult(JSON.parse(event.data))
  })
  source.addEventListener('failed', (event) => {
    source.close()
    handlers.onFailed(JSON.parse(event.data))
  })
  // The browser's own connection event, separate from our `failed` event.
  source.onerror = () => {
    source.close()
    handlers.onFailed({
      code: 'connection_error',
      message: "The briefing service can't be reached. Check that the backend is running.",
      retryable: true,
    })
  }
  return () => source.close()
}

export async function fetchQuote(ticker: string, signal: AbortSignal): Promise<Quote> {
  const response = await fetch(`/api/quotes/${encodeURIComponent(ticker)}`, { signal, cache: 'no-store' })
  if (!response.ok) throw new Error(`Quote request failed with status ${response.status}`)
  return response.json()
}

export async function askQuestion(
  ticker: string,
  question: string,
  history: ChatMessage[],
  useBackupLlm: boolean,
): Promise<ChatResponse> {
  let response: Response
  try {
    response = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ticker, question, history, force_failover: useBackupLlm }),
    })
  } catch {
    throw new Error("The briefing service can't be reached. Check that the backend is running.")
  }
  const body = await response.json().catch(() => null)
  if (!response.ok) {
    throw new Error(body?.message ?? 'Something went wrong with that question. Please try again.')
  }
  return body
}
