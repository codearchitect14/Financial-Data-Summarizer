"""SEC EDGAR access: companies, filings, filing sections and annual financials.

Create one `EdgarClient` per request. It records whether saved data had to stand
in for a live response, so the UI can say so.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
import warnings as python_warnings
from datetime import date
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from dotenv import load_dotenv
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

import cache
from schemas import (
    AnnualFinancials,
    Company,
    CompanyFilings,
    Filing,
    Financials,
    Section,
    SectionKey,
)

logger = logging.getLogger(__name__)
load_dotenv(Path(__file__).with_name(".env"))
# Filings are XHTML, which lxml's HTML parser reads correctly despite this warning.
python_warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/{name}"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"

DAY = 86_400
FOREIGN_ANNUAL_FORMS = ("20-F", "40-F")
MIN_REQUEST_INTERVAL = 0.12  # The SEC allows 10 requests per second.
MIN_SECTION_CHARS = 2_000
STALE_ANNUAL_REPORT_DAYS = 550
# Registrants created by a reorganization, whose 10-K history sits under the old one.
# ExxonMobil Holdings Corp took over the XOM ticker from Exxon Mobil Corp.
PREDECESSOR_CIKS = {2115436: 34088}


class EdgarError(Exception):
    """Base class. Messages are written to be shown to the user."""


class EdgarConfigError(EdgarError):
    pass


class EdgarUnavailableError(EdgarError):
    pass


class TickerNotFoundError(EdgarError):
    pass


class UnsupportedFilerError(EdgarError):
    """The company exists but doesn't file a 10-K, such as an ETF or foreign filer."""


def normalize_ticker(ticker: str) -> str:
    return ticker.strip().upper().replace(".", "-").replace("/", "-")


# --- HTTP ---

_throttle_lock = threading.Lock()
_last_request_at = 0.0


def _throttle() -> None:
    global _last_request_at
    with _throttle_lock:
        wait = _last_request_at + MIN_REQUEST_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.monotonic()


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)


class EdgarClient:
    def __init__(self, user_agent: str | None = None, http: httpx.Client | None = None):
        agent = (user_agent or os.getenv("SEC_USER_AGENT", "")).strip()
        if not agent:
            raise EdgarConfigError("SEC_USER_AGENT is not set in backend/.env.")
        self._http = http or httpx.Client(
            headers={"User-Agent": agent, "Accept-Encoding": "gzip, deflate"},
            timeout=httpx.Timeout(60, connect=10),
            follow_redirects=True,
        )
        self.used_saved_data = False

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, max=4),
        reraise=True,
    )
    def _download(self, url: str) -> httpx.Response:
        _throttle()
        response = self._http.get(url)
        response.raise_for_status()
        return response

    def _fetch(self, url: str, *, max_age: float, as_json: bool) -> Any:
        fresh = cache.read("edgar", url, max_age=max_age)
        if fresh is not None:
            return fresh
        try:
            response = self._download(url)
            value = response.json() if as_json else response.text
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 404:
                raise
            if status == 403:
                # A block won't clear by itself, but saved data can still help.
                logger.warning("SEC returned 403 for %s", url)
            value = self._saved_or_raise(url, exc)
            return value
        except (httpx.TransportError, ValueError) as exc:
            return self._saved_or_raise(url, exc)
        cache.write("edgar", url, value)
        return value

    def _saved_or_raise(self, url: str, exc: Exception) -> Any:
        saved = cache.read("edgar", url)
        if saved is None:
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 403:
                raise EdgarUnavailableError(
                    "The SEC refused the request. Check that SEC_USER_AGENT in "
                    "backend/.env has a real name and email."
                ) from exc
            raise EdgarUnavailableError(
                "SEC EDGAR can't be reached right now, and no saved copy exists."
            ) from exc
        logger.warning("Using saved copy of %s after: %s", url, type(exc).__name__)
        self.used_saved_data = True
        return saved

    def _get_json(self, url: str, max_age: float) -> dict[str, Any]:
        return self._fetch(url, max_age=max_age, as_json=True)

    # --- Companies ---

    def resolve_company(self, ticker: str) -> Company:
        wanted = normalize_ticker(ticker)
        if not re.fullmatch(r"[A-Z0-9-]{1,10}", wanted):
            raise TickerNotFoundError(f'"{ticker.strip()}" isn\'t a valid ticker format.')
        for row in self._get_json(TICKERS_URL, max_age=DAY).values():
            if row["ticker"].upper() == wanted:
                return Company(ticker=wanted, cik=row["cik_str"], name=row["title"])
        raise TickerNotFoundError(
            f'"{wanted}" isn\'t in the SEC\'s list of company tickers. Check the '
            "ticker. Funds such as many ETFs aren't listed."
        )

    # --- Filings ---

    def get_filings(self, company: Company, today: date | None = None) -> CompanyFilings:
        url = SUBMISSIONS_URL.format(name=f"CIK{company.cik:010d}.json")
        submissions = self._get_json(url, max_age=3600)
        pages = [submissions["filings"]["recent"]]
        annual = _latest_of_form(pages[0], "10-K", company.cik)
        quarterly = _latest_of_form(pages[0], "10-Q", company.cik)

        # Heavy filers can push their 10-K out of the `recent` list.
        if annual is None or quarterly is None:
            for page in submissions["filings"].get("files", []):
                older = self._get_json(
                    SUBMISSIONS_URL.format(name=page["name"]), max_age=7 * DAY
                )
                pages.append(older)
                annual = annual or _latest_of_form(older, "10-K", company.cik)
                quarterly = quarterly or _latest_of_form(older, "10-Q", company.cik)
                if annual and quarterly:
                    break

        warnings = []
        predecessor = PREDECESSOR_CIKS.get(company.cik)
        if annual is None and predecessor:
            url = SUBMISSIONS_URL.format(name=f"CIK{predecessor:010d}.json")
            old = self._get_json(url, max_age=3600)
            annual = _latest_of_form(old["filings"]["recent"], "10-K", predecessor)
            if annual:
                warnings.append(
                    f"The latest 10-K was filed by {old['name'].title()}, the "
                    "company's predecessor."
                )

        if annual is None:
            if quarterly is None:
                raise _no_annual_report_error(company, pages)
            warnings.append(
                "No 10-K is on file for this registrant, which may be newly listed or "
                "reorganized. This briefing uses its latest 10-Q only."
            )
            return CompanyFilings(quarterly=quarterly, warnings=warnings)

        age = ((today or date.today()) - date.fromisoformat(annual.filing_date)).days
        if age > STALE_ANNUAL_REPORT_DAYS:
            warnings.append(
                f"The latest 10-K was filed on {annual.filing_date}, so this company "
                "may no longer be reporting."
            )
        if quarterly and quarterly.filing_date <= annual.filing_date:
            quarterly = None
        return CompanyFilings(annual=annual, quarterly=quarterly, warnings=warnings)

    def get_filing_text(self, filing: Filing) -> str:
        cached = cache.read("filing_text", filing.url)
        if cached is not None:
            return cached
        html = self._fetch(filing.url, max_age=365 * DAY, as_json=False)
        text = html_to_text(html)
        cache.write("filing_text", filing.url, text)
        return text

    def get_sections(self, filings: CompanyFilings) -> dict[SectionKey, Section]:
        sections: dict[SectionKey, Section] = {}
        for filing in (filings.annual, filings.quarterly):
            if filing:
                sections |= _extract_sections(filing, self.get_filing_text(filing))
        return sections

    # --- Financials ---

    def get_financials(self, company: Company) -> Financials:
        financials = self._financials_for_cik(company.cik)
        predecessor = PREDECESSOR_CIKS.get(company.cik)
        if predecessor and not financials.years:
            financials = self._financials_for_cik(predecessor)
        return financials

    def _financials_for_cik(self, cik: int) -> Financials:
        try:
            facts = self._get_json(FACTS_URL.format(cik=cik), max_age=DAY)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return Financials(warnings=["The SEC has no financial data for this company."])
            raise
        return financials_from_facts(facts)


def _latest_of_form(page: dict[str, list[Any]], form: str, cik: int) -> Filing | None:
    """Find the newest filing of exactly this form, so 10-K/A amendments are excluded."""
    best: Filing | None = None
    dates = page.get("filingDate", [])
    for index, candidate in enumerate(page.get("form", [])):
        if candidate != form:
            continue
        if best is not None and dates[index] <= best.filing_date:
            continue
        accession = page["accessionNumber"][index]
        document = page["primaryDocument"][index]
        best = Filing(
            form=form,
            accession_number=accession,
            filing_date=dates[index],
            report_date=page.get("reportDate", [None] * (index + 1))[index] or None,
            primary_document=document,
            url=ARCHIVE_URL.format(
                cik=cik, accession=accession.replace("-", ""), document=document
            ),
        )
    return best


def _no_annual_report_error(company: Company, pages: list[dict[str, Any]]) -> UnsupportedFilerError:
    forms = {form for page in pages for form in page.get("form", [])}
    foreign = next((f for f in FOREIGN_ANNUAL_FORMS if f in forms), None)
    if foreign:
        return UnsupportedFilerError(
            f"{company.name} ({company.ticker}) is a foreign filer that reports on "
            f"Form {foreign}. This prototype covers companies that file a 10-K."
        )
    return UnsupportedFilerError(
        f"{company.name} ({company.ticker}) has no 10-K on file. It may be a fund or "
        "ETF, which this prototype doesn't cover."
    )


# --- Filing text ---

_BLOCK_TAGS = [
    "address", "article", "aside", "blockquote", "br", "caption", "center", "dd",
    "div", "dl", "dt", "figcaption", "footer", "h1", "h2", "h3", "h4", "h5", "h6",
    "header", "hr", "li", "main", "ol", "p", "pre", "section", "table", "tbody",
    "td", "tfoot", "th", "thead", "tr", "ul",
]


def html_to_text(html: str) -> str:
    """Convert a filing to single-spaced text.

    Spaces are only added around block elements. Filings often split words and
    figures across inline tags, and adding spaces there would break them.
    """
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "ix:header", "head"]):
        tag.decompose()
    for tag in soup.find_all(_BLOCK_TAGS):
        tag.insert_before(" ")
        tag.insert_after(" ")
    return re.sub(r"\s+", " ", soup.get_text()).strip()


# --- Section extraction ---

_ANY = r"\W{0,6}"
# Text just before a match that shows it's a mention rather than a heading.
_CROSS_REFERENCE_BEFORE = re.compile(
    r"(?:\b(?:see|in|under|within|to|of|and|with|at|by|from|refer|on|this)"
    r"|\bpart\s+(?:i+|\d)\s*,|[\"“‘'(,])\W*$",
    re.IGNORECASE,
)
_ITEM_PREFIX_BEFORE = re.compile(r"\bitem\s*\w+\W*$", re.IGNORECASE)
_AUDITOR_REPORT = r"\breports? of independent registered public accounting firm\b"


class _SectionRule:
    def __init__(
        self,
        key: SectionKey,
        title: str,
        form: str,
        starts: str,
        ends: str,
        name_starts: str | None = None,
        name_ends: str | None = None,
        min_chars: int = MIN_SECTION_CHARS,
    ):
        self.key, self.title, self.form = key, title, form
        self.min_chars = min_chars
        self.starts = re.compile(starts, re.IGNORECASE)
        self.ends = re.compile(ends, re.IGNORECASE)
        self.name_starts = re.compile(name_starts) if name_starts else None
        # A section found by name still stops at the formal item headings.
        self.name_ends = (
            re.compile(f"{ends}|{name_ends}", re.IGNORECASE) if name_ends else None
        )


_RULES = [
    _SectionRule(
        "business", "Business", "10-K",
        starts=rf"\bitems?\s*1\b(?:\s*(?:and|&)\s*2\b)?{_ANY}(?:description\s+of\s+)?business",
        ends=rf"\bitem\s*1a{_ANY}risk|\bitem\s*1b{_ANY}unresolved|\bitem\s*1c{_ANY}cyber"
        rf"|\bitem\s*2{_ANY}(?:description\s+of\s+)?propert|\bitem\s*3{_ANY}legal",
    ),
    _SectionRule(
        "risk_factors", "Risk factors", "10-K",
        starts=rf"\bitem\s*1a{_ANY}risk\s+factors",
        ends=rf"\bitem\s*1b{_ANY}unresolved|\bitem\s*1c{_ANY}cyber"
        rf"|\bitem\s*2{_ANY}(?:description\s+of\s+)?propert|\bitem\s*3{_ANY}legal",
        name_starts=r"\bRISK FACTORS\b|\bRisk [Ff]actors\b",
        name_ends=r"\bunresolved staff comments\b|\bcybersecurity\b(?=\s+(?:risk|governance|strategy))"
        r"|\blegal proceedings\b",
    ),
    _SectionRule(
        "mdna", "Management's discussion and analysis", "10-K",
        starts=rf"\bitem\s*7{_ANY}management.{{0,3}}s?\s+discussion",
        ends=rf"\bitem\s*7a{_ANY}quantitative|\bitem\s*8{_ANY}(?:consolidated\s+)?financial\s+statements",
        name_starts=r"\bMANAGEMENT.{0,3}S DISCUSSION AND ANALYSIS\b"
        r"|\bManagement.{0,3}s [Dd]iscussion and [Aa]nalysis\b",
        name_ends=_AUDITOR_REPORT,
    ),
    _SectionRule(
        "quarterly_mdna", "Quarterly management's discussion and analysis", "10-Q",
        starts=rf"\bitem\s*2{_ANY}management.{{0,3}}s?\s+discussion",
        ends=rf"\bitem\s*3{_ANY}quantitative|\bitem\s*4{_ANY}controls",
        name_starts=r"\bMANAGEMENT.{0,3}S DISCUSSION AND ANALYSIS\b"
        r"|\bManagement.{0,3}s [Dd]iscussion and [Aa]nalysis\b",
        name_ends=_AUDITOR_REPORT,
    ),
    _SectionRule(
        "quarterly_risk_factors", "Risk factor updates", "10-Q",
        starts=rf"\bitem\s*1a{_ANY}risk\s+factors",
        ends=rf"\bitem\s*2{_ANY}unregistered|\bitem\s*3{_ANY}defaults"
        rf"|\bitem\s*5{_ANY}other|\bitem\s*6{_ANY}exhibits",
        # "No material changes" is a valid and short answer here.
        min_chars=60,
    ),
]


def _is_cross_reference(text: str, position: int) -> bool:
    before = text[max(0, position - 40):position]
    # For a match on a section's name, also look past "Item 7." to catch "of Item 7. ..."
    before = _ITEM_PREFIX_BEFORE.sub("", before)
    return bool(_CROSS_REFERENCE_BEFORE.search(before))


def _longest_span(
    text: str, starts: re.Pattern[str], ends: re.Pattern[str]
) -> tuple[int, int] | None:
    """Measure from every heading match to the next real heading, and keep the longest.

    A section's real heading is followed by its whole body, whereas table-of-contents
    entries are followed almost at once by the next heading.
    """
    end_positions = [
        match.start() for match in ends.finditer(text)
        if not _is_cross_reference(text, match.start())
    ]
    best: tuple[int, int] | None = None
    cursor = 0
    for match in starts.finditer(text):
        if _is_cross_reference(text, match.start()):
            continue
        while cursor < len(end_positions) and end_positions[cursor] <= match.end():
            cursor += 1
        if cursor == len(end_positions):
            break
        span = (match.start(), end_positions[cursor])
        if best is None or span[1] - span[0] > best[1] - best[0]:
            best = span
    return best


def extract_section(text: str, rule: _SectionRule, filing_url: str = "") -> Section:
    base = {
        "key": rule.key, "title": rule.title,
        "filing_form": rule.form, "filing_url": filing_url,
    }
    span = _longest_span(text, rule.starts, rule.ends)
    if span and span[1] - span[0] >= rule.min_chars:
        return Section(**base, method="item_heading", text=text[span[0]:span[1]].strip())

    if rule.name_starts and rule.name_ends:
        span = _longest_span(text, rule.name_starts, rule.name_ends)
        if span and span[1] - span[0] >= MIN_SECTION_CHARS:
            return Section(
                **base, method="section_name", text=text[span[0]:span[1]].strip(),
                warning=(
                    f"This filing doesn't use the standard heading for {rule.title.lower()}, "
                    "so the section was located by its name. Check it against the filing."
                ),
            )
    if rule.key == "quarterly_risk_factors":
        # Many 10-Qs have no update, so its absence isn't an extraction failure.
        return Section(**base, method="not_found")
    return Section(
        **base, method="not_found",
        warning=f"{rule.title} couldn't be located in this {rule.form}. See the filing directly.",
    )


def _extract_sections(filing: Filing, text: str) -> dict[SectionKey, Section]:
    return {
        rule.key: extract_section(text, rule, filing.url)
        for rule in _RULES
        if rule.form == filing.form
    }


# --- Financials ---

_REVENUE_TAGS = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "RevenuesNetOfInterestExpense",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "SalesRevenueNet",
    "SalesRevenueGoodsNet",
)
_NET_INCOME_TAGS = ("NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic")
_EPS_TAGS = ("EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted", "EarningsPerShareBasic")
_MIN_YEAR_DAYS, _MAX_YEAR_DAYS = 340, 380
_YEARS_TO_SHOW = 4


def _annual_values(fact: dict[str, Any], unit: str) -> dict[str, dict[str, Any]]:
    """Return annual values by period end, using the latest filed value for each.

    Periods come from each entry's dates, not its `fy` field. `fy` is the year of
    the filing, so a filing's prior-year comparatives share it. The latest filed
    value also reflects restatements and stock splits.
    """
    by_end: dict[str, dict[str, Any]] = {}
    for entry in fact.get("units", {}).get(unit, []):
        if not entry.get("form", "").startswith("10-K") or "start" not in entry:
            continue
        days = (date.fromisoformat(entry["end"]) - date.fromisoformat(entry["start"])).days
        if not _MIN_YEAR_DAYS <= days <= _MAX_YEAR_DAYS:
            continue
        current = by_end.get(entry["end"])
        if current is None or entry.get("filed", "") >= current.get("filed", ""):
            by_end[entry["end"]] = entry
    return by_end


def _best_series(
    gaap: dict[str, Any], tags: tuple[str, ...], unit: str
) -> dict[str, dict[str, Any]]:
    """Pick the tag with the newest data, as companies change tags over time."""
    best: dict[str, dict[str, Any]] = {}
    for tag in tags:
        series = _annual_values(gaap.get(tag, {}), unit)
        if series and (not best or max(series) > max(best)):
            best = series
    return best


def financials_from_facts(facts: dict[str, Any]) -> Financials:
    gaap = facts.get("facts", {}).get("us-gaap", {})
    revenue = _best_series(gaap, _REVENUE_TAGS, "USD")
    net_income = _best_series(gaap, _NET_INCOME_TAGS, "USD")
    eps = _best_series(gaap, _EPS_TAGS, "USD/shares")

    periods = sorted(set(revenue) | set(net_income) | set(eps), reverse=True)[:_YEARS_TO_SHOW]
    years = []
    for end in periods:
        entries = [series[end] for series in (revenue, net_income, eps) if end in series]
        years.append(
            AnnualFinancials(
                period_start=entries[0]["start"],
                period_end=end,
                revenue=revenue.get(end, {}).get("val"),
                net_income=net_income.get(end, {}).get("val"),
                eps_diluted=eps.get(end, {}).get("val"),
                source_accession=entries[0].get("accn"),
            )
        )

    warnings = []
    if not years:
        warnings.append("No annual financial data in US GAAP format was found.")
    for label, series in (("Revenue", revenue), ("Net income", net_income), ("EPS", eps)):
        if years and not any(y in series for y in periods):
            warnings.append(f"{label} wasn't found in the SEC's financial data.")
    return Financials(years=years, warnings=warnings)
