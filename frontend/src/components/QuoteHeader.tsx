import { ArrowDownRight, ArrowUpRight } from 'lucide-react'
import type { Company, Quote } from '../api/types'
import { QUOTE_REFRESH_MS, useLiveQuote } from '../api/useLiveQuote'
import {
  formatCompact,
  formatDateTime,
  formatPercent,
  formatPrice,
  formatRange,
  formatSigned,
} from '../lib/format'

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-4 py-3">
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className="mt-1 text-sm font-medium tabular-nums">{value}</dd>
    </div>
  )
}

export function QuoteHeader({ company, quote: initialQuote }: { company: Company; quote: Quote | null }) {
  const { quote, paused } = useLiveQuote(company.ticker, initialQuote)
  const currency = quote?.currency ?? 'USD'
  const rising = (quote?.change ?? 0) >= 0
  const ChangeIcon = rising ? ArrowUpRight : ArrowDownRight

  return (
    <header>
      <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-3">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">{company.name}</h2>
          <p className="mt-0.5 text-sm text-slate-500">
            {company.ticker}
            {quote?.exchange ? ` · ${quote.exchange}` : ''}
          </p>
        </div>
        {quote ? (
          <div className="text-right">
            <p className="text-3xl font-semibold tracking-tight tabular-nums">
              {formatPrice(quote.price, currency)}
            </p>
            {quote.change != null && (
              <p
                className={`mt-0.5 flex items-center justify-end gap-1 text-sm font-medium tabular-nums ${
                  rising ? 'text-emerald-700' : 'text-red-700'
                }`}
              >
                <ChangeIcon aria-hidden className="size-4" />
                {formatSigned(quote.change, currency)} ({formatPercent(quote.change_percent)})
              </p>
            )}
            <p className="mt-0.5 text-xs text-slate-500">
              {quote.is_saved ? 'Saved quote from ' : 'As of '}
              {formatDateTime(quote.as_of, true)}
            </p>
            <p className={`mt-0.5 text-xs ${paused ? 'font-medium text-amber-800' : 'text-slate-500'}`}>
              {paused
                ? 'Live updates paused, showing the last price'
                : `Updates every ${QUOTE_REFRESH_MS / 1000} s`}
            </p>
          </div>
        ) : (
          <p className="text-sm text-slate-500">Quote unavailable</p>
        )}
      </div>
      {quote && (
        <dl className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Metric label="Previous close" value={formatPrice(quote.previous_close, currency)} />
          <Metric label="Day range" value={formatRange(quote.day_low, quote.day_high, currency)} />
          <Metric label="52-week range" value={formatRange(quote.year_low, quote.year_high, currency)} />
          <Metric label="Market cap" value={formatCompact(quote.market_cap, currency)} />
        </dl>
      )}
    </header>
  )
}
