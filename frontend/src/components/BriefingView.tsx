import { TriangleAlert } from 'lucide-react'
import type { Briefing, Filing } from '../api/types'
import { formatDate, formatDateTime } from '../lib/format'
import { ChatPanel } from './ChatPanel'
import { FinancialTable } from './FinancialTable'
import { QuoteHeader } from './QuoteHeader'
import { SectionCard } from './SectionCard'

function FilingLink({ filing }: { filing: Filing }) {
  return (
    <li>
      <a href={filing.url} target="_blank" rel="noreferrer" className="font-medium text-blue-700 hover:underline">
        Form {filing.form}
      </a>
      <span className="text-slate-500"> · filed {formatDate(filing.filing_date)}</span>
    </li>
  )
}

const PROVIDER_NAME = { gemini: 'Gemini', groq: 'Groq' }

export function BriefingView({ briefing, useBackupLlm }: { briefing: Briefing; useBackupLlm: boolean }) {
  const { verification, llm } = briefing
  const sections = briefing.sections.filter((s) => s.claims.length > 0 || s.warning)

  return (
    <div className="mt-6 space-y-5">
      {briefing.warnings.length > 0 && (
        <div role="status" className="space-y-1 rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900">
          {briefing.warnings.map((warning) => (
            <p key={warning} className="flex gap-2">
              <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0" />
              {warning}
            </p>
          ))}
        </div>
      )}

      {/* The key restarts live updates from each new briefing's quote. */}
      <QuoteHeader key={briefing.generated_at} company={briefing.company} quote={briefing.quote} />

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="min-w-0 space-y-5">
          <FinancialTable financials={briefing.financials} />
          {sections.map((section) => (
            <SectionCard key={section.key} section={section} />
          ))}
        </div>

        <aside className="space-y-5">
          {/* The key starts a new conversation for each new briefing. */}
          <ChatPanel key={briefing.generated_at} ticker={briefing.company.ticker} useBackupLlm={useBackupLlm} />
          {verification.total_claims > 0 && (
            <section className="rounded-lg border border-slate-200 bg-white p-5">
              <h3 className="font-semibold">Trust check</h3>
              <p className="mt-2 text-2xl font-semibold tabular-nums">
                {verification.verified_claims} of {verification.total_claims}
              </p>
              <p className="text-sm text-slate-600">summary quotes found word for word in the filings read</p>
              <p className="mt-2 text-xs leading-5 text-slate-500">
                This confirms each quote is real and contains the point's figures. Review the quote to judge
                whether the summary is a fair reading.
              </p>
            </section>
          )}

          {briefing.client_questions.length > 0 && (
            <section className="rounded-lg border border-slate-200 bg-white p-5">
              <h3 className="font-semibold">Questions a client may ask</h3>
              <ul className="mt-2 list-disc space-y-2 pl-4 text-sm leading-6">
                {briefing.client_questions.map((question) => (
                  <li key={question}>{question}</li>
                ))}
              </ul>
            </section>
          )}

          <section className="rounded-lg border border-slate-200 bg-white p-5 text-sm">
            <h3 className="font-semibold">Sources</h3>
            <ul className="mt-2 space-y-1">
              {briefing.annual_filing && <FilingLink filing={briefing.annual_filing} />}
              {briefing.quarterly_filing && <FilingLink filing={briefing.quarterly_filing} />}
            </ul>
            {briefing.annual_filing && !briefing.quarterly_filing && (
              <p className="mt-2 text-xs text-slate-500">The 10-K is the newest report on file.</p>
            )}
            <p className="mt-3 text-xs leading-5 text-slate-500">
              {llm && (
                <>
                  Summarized by {PROVIDER_NAME[llm.provider]} ({llm.model})
                  {llm.from_saved ? ', saved from an earlier run' : ''}.{' '}
                </>
              )}
              Generated {formatDateTime(briefing.generated_at)}.
            </p>
          </section>
        </aside>
      </div>
    </div>
  )
}
