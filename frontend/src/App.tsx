import { CircleAlert } from 'lucide-react'
import { useRef, useState } from 'react'
import { streamBriefing } from './api/client'
import type { Briefing, BriefingFailure } from './api/types'
import { BriefingView } from './components/BriefingView'
import { ProgressSteps } from './components/ProgressSteps'
import { TickerSearch } from './components/TickerSearch'

const SUGGESTIONS = ['AAPL', 'MSFT', 'NVDA', 'JPM', 'XOM']

type State =
  | { status: 'idle' }
  | { status: 'loading'; ticker: string; step: string | null }
  | { status: 'done'; briefing: Briefing }
  | { status: 'failed'; ticker: string; failure: BriefingFailure }

export default function App() {
  const [state, setState] = useState<State>({ status: 'idle' })
  const [useBackupLlm, setUseBackupLlm] = useState(false)
  const stopStream = useRef<(() => void) | null>(null)

  // Started from user actions, not an effect, so React's Strict Mode can't run it twice.
  function start(ticker: string) {
    stopStream.current?.()
    setState({ status: 'loading', ticker, step: null })
    stopStream.current = streamBriefing(ticker, useBackupLlm, {
      onProgress: ({ step }) => setState({ status: 'loading', ticker, step }),
      onResult: (briefing) => setState({ status: 'done', briefing }),
      onFailed: (failure) => setState({ status: 'failed', ticker, failure }),
    })
  }

  return (
    <div className="flex min-h-screen flex-col">
      <div className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-x-8 gap-y-3 px-4 py-3 sm:px-6">
          <h1 className="font-semibold tracking-tight">Stock Briefing Assistant</h1>
          <TickerSearch busy={state.status === 'loading'} onSubmit={start} />
        </div>
      </div>

      <main className="mx-auto w-full max-w-6xl flex-1 px-4 pb-10 sm:px-6">
        {state.status === 'idle' && (
          <div className="mx-auto mt-16 max-w-xl text-center">
            <h2 className="text-2xl font-semibold tracking-tight">Get up to speed on a stock</h2>
            <p className="mt-2 text-slate-600">
              Current quote, reported financials and a summary of recent SEC filings, with every point
              checked against its source.
            </p>
            <div className="mt-5 flex flex-wrap justify-center gap-2">
              {SUGGESTIONS.map((ticker) => (
                <button
                  key={ticker}
                  type="button"
                  onClick={() => start(ticker)}
                  className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium hover:bg-slate-100"
                >
                  {ticker}
                </button>
              ))}
            </div>
          </div>
        )}

        {state.status === 'loading' && <ProgressSteps ticker={state.ticker} current={state.step} />}

        {state.status === 'failed' && (
          <div role="alert" className="mx-auto mt-10 max-w-lg rounded-lg border border-red-200 bg-white p-6">
            <h2 className="flex items-center gap-2 font-semibold text-red-800">
              <CircleAlert aria-hidden className="size-5" />
              No briefing for {state.ticker}
            </h2>
            <p className="mt-2 text-sm leading-6 text-slate-700">{state.failure.message}</p>
            {state.failure.retryable && (
              <button
                type="button"
                onClick={() => start(state.ticker)}
                className="mt-4 rounded-md bg-blue-700 px-4 py-2 text-sm font-medium text-white hover:bg-blue-800"
              >
                Try again
              </button>
            )}
          </div>
        )}

        {state.status === 'done' && <BriefingView briefing={state.briefing} useBackupLlm={useBackupLlm} />}
      </main>

      <footer className="border-t border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-x-6 gap-y-2 px-4 py-3 text-xs text-slate-500 sm:px-6">
          <p>Information only, not investment advice. Sources: SEC EDGAR and Yahoo Finance (may be delayed).</p>
          <label className="flex cursor-pointer items-center gap-1.5">
            <input
              type="checkbox"
              checked={useBackupLlm}
              onChange={(event) => setUseBackupLlm(event.target.checked)}
            />
            Use backup LLM (Groq)
          </label>
        </div>
      </footer>
    </div>
  )
}
