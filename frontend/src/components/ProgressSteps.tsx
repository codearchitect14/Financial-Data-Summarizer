import { Check, Circle, LoaderCircle } from 'lucide-react'

const STEPS = [
  ['company', 'Find the company and its filings'],
  ['quote', 'Get the current quote'],
  ['financials', 'Read annual financials'],
  ['filings', 'Read the latest SEC filings'],
  ['analysis', 'Summarize the filings'],
  ['verification', 'Check each quote against the filings'],
] as const

export function ProgressSteps({ ticker, current }: { ticker: string; current: string | null }) {
  const currentIndex = STEPS.findIndex(([step]) => step === current)
  return (
    <section
      aria-live="polite"
      aria-label={`Building the briefing for ${ticker}`}
      className="mx-auto mt-10 max-w-md rounded-lg border border-slate-200 bg-white p-6"
    >
      <h2 className="font-semibold">Building the {ticker} briefing</h2>
      <p className="mt-1 text-sm text-slate-500">A new briefing usually takes under a minute.</p>
      <ol className="mt-5 space-y-3">
        {STEPS.map(([step, label], index) => {
          const done = index < currentIndex
          const active = index === currentIndex
          return (
            <li key={step} className="flex items-center gap-3 text-sm">
              {done && <Check aria-hidden className="size-4 text-emerald-700" />}
              {active && <LoaderCircle aria-hidden className="size-4 animate-spin text-blue-700" />}
              {!done && !active && <Circle aria-hidden className="size-4 text-slate-300" />}
              <span className={active ? 'font-medium' : done ? 'text-slate-700' : 'text-slate-400'}>
                {label}
                <span className="sr-only">{done ? ' (done)' : active ? ' (in progress)' : ''}</span>
              </span>
            </li>
          )
        })}
      </ol>
    </section>
  )
}
