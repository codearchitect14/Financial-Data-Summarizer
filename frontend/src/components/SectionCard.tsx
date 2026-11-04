import { CircleAlert, CircleCheck, ExternalLink } from 'lucide-react'
import type { BriefingSection, Claim } from '../api/types'

const UNVERIFIED_LABEL = {
  quote_not_found: 'Quote not found in the filings',
  figures_not_in_quote: 'Figures not in the quote',
} as const

function ClaimItem({ claim }: { claim: Claim }) {
  const verified = claim.status === 'verified'
  return (
    <li className="py-3 first:pt-0 last:pb-0">
      <p className="text-sm leading-6">{claim.text}</p>
      <details className="group mt-1" open={!verified}>
        <summary className="inline-flex cursor-pointer items-center gap-1.5 text-xs font-medium">
          {claim.status === 'verified' ? (
            <span className="inline-flex items-center gap-1 text-emerald-800">
              <CircleCheck aria-hidden className="size-3.5" />
              Quote verified
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 text-amber-800">
              <CircleAlert aria-hidden className="size-3.5" />
              {UNVERIFIED_LABEL[claim.status]}
            </span>
          )}
          <span className="font-normal text-slate-500 group-open:hidden">· Show quote</span>
        </summary>
        <blockquote
          className={`mt-2 border-l-2 pl-3 text-xs leading-5 text-slate-600 ${
            verified ? 'border-slate-300' : 'border-amber-400'
          }`}
        >
          {claim.supporting_quote}
        </blockquote>
      </details>
    </li>
  )
}

export function SectionCard({ section }: { section: BriefingSection }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h3 className="font-semibold">{section.title}</h3>
        <a
          href={section.filing_url}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 text-xs font-medium text-blue-700 hover:underline"
        >
          Open {section.filing_form}
          <ExternalLink aria-hidden className="size-3" />
          <span className="sr-only">(opens in a new tab)</span>
        </a>
      </div>
      {section.truncated && (
        <p className="mt-1 text-xs text-slate-500">
          This section is long, so the summary is based on its opening part.
        </p>
      )}
      {section.warning && <p className="mt-1 text-xs text-amber-800">{section.warning}</p>}
      {section.claims.length > 0 && (
        <ul className="mt-3 divide-y divide-slate-100">
          {section.claims.map((claim) => (
            <ClaimItem key={claim.text} claim={claim} />
          ))}
        </ul>
      )}
    </section>
  )
}
