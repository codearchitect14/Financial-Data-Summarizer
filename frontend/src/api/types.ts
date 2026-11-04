// Keep in line with backend/schemas.py.

export interface Company {
  ticker: string
  cik: number
  name: string
}

export interface Filing {
  form: string
  accession_number: string
  filing_date: string
  report_date: string | null
  primary_document: string
  url: string
}

export interface AnnualFinancials {
  period_start: string
  period_end: string
  revenue: number | null
  net_income: number | null
  eps_diluted: number | null
  source_accession: string | null
}

export interface Financials {
  currency: string
  years: AnnualFinancials[]
  warnings: string[]
}

export interface Quote {
  ticker: string
  price: number
  previous_close: number | null
  change: number | null
  change_percent: number | null
  currency: string | null
  day_low: number | null
  day_high: number | null
  year_low: number | null
  year_high: number | null
  market_cap: number | null
  exchange: string | null
  as_of: string | null
  source: 'yfinance' | 'yahoo_chart' | 'saved'
  is_saved: boolean
}

export type VerificationStatus = 'verified' | 'quote_not_found' | 'figures_not_in_quote'

export interface Claim {
  text: string
  supporting_quote: string
  status: VerificationStatus
}

export interface BriefingSection {
  key: string
  title: string
  filing_form: string
  filing_url: string
  claims: Claim[]
  truncated: boolean
  warning: string | null
}

export interface LLMInfo {
  provider: 'gemini' | 'groq'
  model: string
  reduced: boolean
  fell_back: boolean
  fallback_reason: string | null
  input_tokens: number
  output_tokens: number
  elapsed_seconds: number
  from_saved: boolean
}

export interface Briefing {
  company: Company
  quote: Quote | null
  financials: Financials
  annual_filing: Filing | null
  quarterly_filing: Filing | null
  sections: BriefingSection[]
  client_questions: string[]
  verification: { total_claims: number; verified_claims: number }
  llm: LLMInfo | null
  warnings: string[]
  generated_at: string
  elapsed_seconds: number
}

export interface BriefingFailure {
  code: string
  message: string
  retryable: boolean
}

export interface ProgressEvent {
  step: string
  message: string
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface ChatResponse {
  answer: string
  tools_used: string[]
  unsupported_figures: string[]
  sources: { label: string; url: string | null; filing_date: string | null }[]
  provider: 'gemini' | 'groq'
  model: string
  fell_back: boolean
  input_tokens: number
  output_tokens: number
  elapsed_seconds: number
}
