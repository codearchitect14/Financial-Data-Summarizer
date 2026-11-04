import { CircleAlert, ExternalLink, Send } from 'lucide-react'
import { useRef, useState, type FormEvent } from 'react'
import { askQuestion } from '../api/client'
import type { ChatMessage, ChatResponse } from '../api/types'

const STARTER = 'How did revenue change, and what risks does management flag?'

interface Turn {
  question: string
  response: ChatResponse
}

function Answer({ response }: { response: ChatResponse }) {
  return (
    <div className="rounded-md bg-slate-50 p-3">
      <p className="text-sm leading-6 whitespace-pre-wrap">{response.answer}</p>
      {response.unsupported_figures.length > 0 && (
        <p className="mt-2 flex gap-1.5 text-xs leading-5 text-amber-800">
          <CircleAlert aria-hidden className="mt-0.5 size-3.5 shrink-0" />
          Not found in the sources, so check before using: {response.unsupported_figures.join(', ')}
        </p>
      )}
      <div className="mt-2 text-xs leading-5 text-slate-500">
        {response.tools_used.length > 0 && <p>Used: {response.tools_used.join(', ')}</p>}
        {response.sources.some((source) => source.url) && (
          <p className="flex flex-wrap gap-x-3">
            {response.sources
              .filter((source) => source.url)
              .map((source) => (
                <a
                  key={source.url}
                  href={source.url ?? undefined}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 font-medium text-blue-700 hover:underline"
                >
                  {source.label}
                  <ExternalLink aria-hidden className="size-3" />
                  <span className="sr-only">(opens in a new tab)</span>
                </a>
              ))}
          </p>
        )}
        <p>Answered by {response.provider === 'gemini' ? 'Gemini' : 'Groq'}{response.fell_back ? ' (backup)' : ''}</p>
      </div>
    </div>
  )
}

export function ChatPanel({ ticker, useBackupLlm }: { ticker: string; useBackupLlm: boolean }) {
  const [turns, setTurns] = useState<Turn[]>([])
  const [question, setQuestion] = useState('')
  const [pending, setPending] = useState<string | null>(null)
  const [error, setError] = useState<{ question: string; message: string } | null>(null)
  const end = useRef<HTMLDivElement>(null)

  async function ask(text: string) {
    const trimmed = text.trim()
    if (!trimmed || pending) return
    setPending(trimmed)
    setError(null)
    setQuestion('')
    const history: ChatMessage[] = turns.flatMap((turn) => [
      { role: 'user', content: turn.question },
      { role: 'assistant', content: turn.response.answer },
    ])
    try {
      const response = await askQuestion(ticker, trimmed, history, useBackupLlm)
      setTurns((current) => [...current, { question: trimmed, response }])
    } catch (caught) {
      setError({ question: trimmed, message: (caught as Error).message })
    } finally {
      setPending(null)
      requestAnimationFrame(() => end.current?.scrollIntoView({ block: 'nearest' }))
    }
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    void ask(question)
  }

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5" aria-label="Follow-up questions">
      <h3 className="font-semibold">Ask about {ticker}</h3>
      <p className="mt-0.5 text-xs leading-5 text-slate-500">
        Answers come from SEC filings, financials and the quote. They aren't quote-checked like the summary.
      </p>

      <div aria-live="polite" className="mt-3 max-h-[28rem] space-y-3 overflow-y-auto">
        {turns.map((turn, index) => (
          <div key={index} className="space-y-2">
            <p className="text-sm font-medium">{turn.question}</p>
            <Answer response={turn.response} />
          </div>
        ))}
        {pending && (
          <div className="space-y-2">
            <p className="text-sm font-medium">{pending}</p>
            <p className="animate-pulse rounded-md bg-slate-50 p-3 text-sm text-slate-500">
              Checking the sources. This can take up to a minute…
            </p>
          </div>
        )}
        {error && (
          <div role="alert" className="rounded-md border border-red-200 p-3 text-sm text-red-800">
            <p>{error.message}</p>
            <button
              type="button"
              onClick={() => void ask(error.question)}
              className="mt-1 text-xs font-medium text-blue-700 hover:underline"
            >
              Try again
            </button>
          </div>
        )}
        <div ref={end} />
      </div>

      {turns.length === 0 && !pending && !error && (
        <button
          type="button"
          onClick={() => void ask(STARTER)}
          className="mt-3 w-full rounded-md border border-slate-300 px-3 py-2 text-left text-xs leading-5 hover:bg-slate-100"
        >
          {STARTER}
        </button>
      )}

      <form onSubmit={handleSubmit} className="mt-3 flex gap-2">
        <label htmlFor="question" className="sr-only">
          Your question about {ticker}
        </label>
        <input
          id="question"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          maxLength={2000}
          autoComplete="off"
          placeholder="Ask a question"
          className="h-9 min-w-0 flex-1 rounded-md border border-slate-300 px-3 text-sm placeholder:text-slate-400"
        />
        <button
          type="submit"
          disabled={!question.trim() || pending !== null}
          aria-label="Send question"
          className="flex size-9 shrink-0 items-center justify-center rounded-md bg-blue-700 text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:bg-slate-300"
        >
          <Send aria-hidden className="size-4" />
        </button>
      </form>
    </section>
  )
}
