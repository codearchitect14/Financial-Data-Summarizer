"""Data shared by the backend modules and returned by the API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Company(BaseModel):
    ticker: str
    cik: int
    name: str


class Filing(BaseModel):
    form: str
    accession_number: str
    filing_date: str
    report_date: str | None = None
    primary_document: str
    url: str


class CompanyFilings(BaseModel):
    # None for a newly listed company that hasn't filed its first 10-K yet.
    annual: Filing | None = None
    # Only set when filed after the annual report, so it's genuinely newer.
    quarterly: Filing | None = None
    warnings: list[str] = []


SectionKey = Literal[
    "business", "risk_factors", "mdna", "quarterly_mdna", "quarterly_risk_factors"
]


class Section(BaseModel):
    key: SectionKey
    title: str
    filing_form: str
    filing_url: str
    # How the text was found: the formal item heading, or the section's name.
    method: Literal["item_heading", "section_name", "not_found"]
    text: str = ""
    warning: str | None = None

    @property
    def found(self) -> bool:
        return self.method != "not_found"


class AnnualFinancials(BaseModel):
    period_start: str
    period_end: str
    revenue: float | None = None
    net_income: float | None = None
    eps_diluted: float | None = None
    # The filing that most recently reported each figure, for source links.
    source_accession: str | None = None


class Financials(BaseModel):
    currency: str = "USD"
    years: list[AnnualFinancials] = []  # Newest first.
    warnings: list[str] = []


QuoteSource = Literal["yfinance", "yahoo_chart", "saved"]


class Quote(BaseModel):
    ticker: str
    price: float
    previous_close: float | None = None
    change: float | None = None
    change_percent: float | None = None
    currency: str | None = None
    day_low: float | None = None
    day_high: float | None = None
    year_low: float | None = None
    year_high: float | None = None
    market_cap: float | None = None
    exchange: str | None = None
    as_of: str | None = None  # ISO 8601 in UTC, from the market data itself.
    source: QuoteSource
    is_saved: bool = False  # True when live sources failed and this is an old quote.


VerificationStatus = Literal[
    "verified",  # The quote is in the filing and contains the claim's figures.
    "quote_not_found",  # The quote is missing, too short, or isn't in the filing.
    "figures_not_in_quote",  # The quote is real, but doesn't back the claim's numbers.
]


class Claim(BaseModel):
    text: str
    supporting_quote: str
    status: VerificationStatus

    @property
    def verified(self) -> bool:
        return self.status == "verified"


class BriefingSection(BaseModel):
    key: SectionKey
    title: str
    filing_form: str
    filing_url: str
    claims: list[Claim] = []
    # Only part of a long section is read, so the page has to say so.
    truncated: bool = False
    warning: str | None = None


class LLMInfo(BaseModel):
    provider: Literal["gemini", "groq"]
    model: str
    reduced: bool
    fell_back: bool = False
    fallback_reason: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    elapsed_seconds: float = 0
    from_saved: bool = False  # True when this analysis was generated on an earlier run.


class VerificationSummary(BaseModel):
    total_claims: int = 0
    verified_claims: int = 0


class Briefing(BaseModel):
    company: Company
    quote: Quote | None = None
    financials: Financials
    annual_filing: Filing | None = None
    quarterly_filing: Filing | None = None
    sections: list[BriefingSection] = []
    client_questions: list[str] = []
    verification: VerificationSummary = VerificationSummary()
    llm: LLMInfo | None = None  # None when no analysis could be produced.
    warnings: list[str] = []
    generated_at: str
    elapsed_seconds: float = 0


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class ChatRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=12)
    question: str = Field(min_length=1, max_length=2000)
    history: list[ChatMessage] = Field(default=[], max_length=20)
    force_failover: bool = False


class ChatSource(BaseModel):
    label: str
    url: str | None = None
    filing_date: str | None = None


class ChatResponse(BaseModel):
    answer: str
    tools_used: list[str] = []
    # Dollar or percent figures in the answer that no tool result contains.
    unsupported_figures: list[str] = []
    sources: list[ChatSource] = []
    provider: Literal["gemini", "groq"]
    model: str
    fell_back: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    elapsed_seconds: float = 0
