"""EDGAR rules, using layouts seen in real filings. No network."""

from datetime import date

import httpx
import pytest

import cache
import edgar
from edgar import (
    EdgarClient,
    EdgarConfigError,
    EdgarUnavailableError,
    TickerNotFoundError,
    UnsupportedFilerError,
    financials_from_facts,
    html_to_text,
    normalize_ticker,
)
from schemas import Company

RULES = {rule.key: rule for rule in edgar._RULES}
BODY = "Substantive discussion of the matter at hand. " * 100  # About 4,600 characters.
TOC = (
    "Item 1. Business 3 Item 1A. Risk Factors 9 Item 1B. Unresolved Staff Comments 20 "
    "Item 2. Properties 21 Item 7. Management's Discussion and Analysis 25 "
    "Item 7A. Quantitative and Qualitative Disclosures 30 Item 8. Financial Statements 31 "
)


def extract(key, text):
    return edgar.extract_section(text, RULES[key], "https://example.test/filing")


@pytest.fixture(autouse=True)
def temporary_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(edgar, "MIN_REQUEST_INTERVAL", 0)


@pytest.mark.parametrize(
    "raw, expected",
    [("aapl", "AAPL"), (" brk.b ", "BRK-B"), ("BRK/B", "BRK-B"), ("BF-B", "BF-B")],
)
def test_normalize_ticker(raw, expected):
    assert normalize_ticker(raw) == expected


# --- Section extraction ---


def test_real_heading_beats_table_of_contents():
    text = f"{TOC} Item 1A. Risk Factors {BODY} Item 1B. Unresolved Staff Comments None."
    section = extract("risk_factors", text)
    assert section.method == "item_heading"
    assert section.text.startswith("Item 1A. Risk Factors Substantive")
    assert section.text.endswith(BODY.strip())


def test_later_cross_reference_does_not_replace_the_section():
    # On NVDA, JPM and BAC the last "Item 1A" is a mention, so "last match" fails.
    text = (
        f"{TOC} Item 1A. Risk Factors {BODY} Item 1B. Unresolved Staff Comments None. "
        "Item 2. Properties Offices. For more, see Item 1A. Risk Factors of this report."
    )
    assert extract("risk_factors", text).text.startswith("Item 1A. Risk Factors Substantive")


def test_cross_reference_inside_a_section_does_not_end_it():
    text = (
        f"{TOC} Item 1A. Risk Factors {BODY} as described in Item 2. Properties below. "
        f"{BODY} Item 2. Properties Offices."
    )
    section = extract("risk_factors", text)
    assert "described in Item 2" in section.text
    assert section.text.endswith(BODY.strip())


def test_text_after_part_reference_is_a_mention():
    # BAC: "set forth under Part 1, Item 1A. Risk Factors of the 2025 Annual Report".
    assert edgar._is_cross_reference("set forth under Part 1, Item 1A", 24)
    assert edgar._is_cross_reference("set forth under Part I, Item 1A", 24)


def test_real_heading_after_item_six_is_not_a_mention():
    text = "Item 6. [Reserved] Item 7. Management's Discussion"
    assert not edgar._is_cross_reference(text, text.index("Item 7."))


def test_case_differences_are_handled():
    text = f"ITEM 1A. RISK FACTORS {BODY} ITEM 1B. UNRESOLVED STAFF COMMENTS None."
    assert extract("risk_factors", text).method == "item_heading"


def test_combined_items_one_and_two_heading():
    text = f"Items 1 and 2. Business and Properties {BODY} Item 1A. Risk Factors x"
    assert extract("business", text).method == "item_heading"


def test_section_without_item_heading_is_found_by_name_and_warned():
    # BAC's MD&A has no "Item 7." heading in the body, only its name.
    text = (
        f"{TOC} forth on pages 36 through 44 of Item 7. Management's Discussion and "
        f"Analysis of operations. {BODY} Bank of America Management's Discussion and "
        f"Analysis of Financial Condition {BODY} Item 7A. Quantitative and Qualitative"
    )
    section = extract("mdna", text)
    assert section.method == "section_name"
    assert section.warning
    assert section.text.startswith("Management's Discussion and Analysis of Financial")
    assert not section.text.startswith("Management's Discussion and Analysis of operations")


def test_name_search_stops_at_the_auditor_report():
    # JPM's formal Item 7A comes before its MD&A, so the auditor's report ends it.
    text = (
        f"Item 7. Management's Discussion and Analysis 33 Item 7A. Quantitative 34 "
        f"Management's discussion and analysis {BODY} "
        "Report of Independent Registered Public Accounting Firm The opinion."
    )
    section = extract("mdna", text)
    assert section.method == "section_name"
    assert "The opinion" not in section.text


def test_missing_section_is_reported_with_a_warning():
    section = extract("risk_factors", "No such content here.")
    assert not section.found
    assert section.text == ""
    assert section.warning


def test_short_quarterly_risk_update_is_valid():
    text = (
        "Item 1A. Risk Factors 51 Item 2. Unregistered Sales 51 "
        "Item 1A. Risk Factors There are no material changes from the risk factors set "
        "forth in the Annual Report. Item 2. Unregistered Sales of Equity Securities"
    )
    section = extract("quarterly_risk_factors", text)
    assert section.found
    assert "no material changes" in section.text


def test_absent_quarterly_risk_update_is_not_treated_as_a_failure():
    section = extract("quarterly_risk_factors", "Nothing relevant.")
    assert not section.found
    assert section.warning is None


# --- Filing text ---


def test_inline_tags_do_not_split_words_but_cells_stay_apart():
    html = """<html><head><title>Hidden title</title></head><body>
      <ix:header><p>Hidden metadata</p></ix:header><style>p {color: red}</style>
      <p>Rev<span>enue was $<ix:nonfraction>1,234</ix:nonfraction></span> million.</p>
      <table><tr><td>Sales</td><td>500</td></tr></table></body></html>"""
    text = html_to_text(html)
    assert "Revenue was $1,234 million." in text
    assert "Sales 500" in text
    assert "Hidden" not in text and "color" not in text


# --- Finding filings ---


def page(*rows):
    forms, dates, numbers, documents = [], [], [], []
    for index, (form, filed) in enumerate(rows):
        forms.append(form)
        dates.append(filed)
        numbers.append(f"0000000000-26-{index:06d}")
        documents.append(f"doc{index}.htm")
    return {
        "form": forms, "filingDate": dates, "accessionNumber": numbers,
        "primaryDocument": documents, "reportDate": [""] * len(rows),
    }


def client_for(routes):
    """A real client whose responses come from `routes`, keyed by the URL's ending."""

    def respond(request):
        for ending, payload in routes.items():
            if str(request.url).endswith(ending):
                if isinstance(payload, int):
                    return httpx.Response(payload, request=request)
                return httpx.Response(200, json=payload, request=request)
        return httpx.Response(404, request=request)

    return EdgarClient("Test tester@example.test", http=httpx.Client(transport=httpx.MockTransport(respond)))


COMPANY = Company(ticker="ACME", cik=123, name="Acme Corp")
SUBMISSIONS = "CIK0000000123.json"


def submissions(recent, files=()):
    return {"name": "Acme", "filings": {"recent": recent, "files": list(files)}}


def test_older_quarterly_report_is_dropped():
    # Apple's latest 10-Q predates its latest 10-K.
    client = client_for({SUBMISSIONS: submissions(page(("10-K", "2026-11-03"), ("10-Q", "2026-07-31")))})
    filings = client.get_filings(COMPANY, today=date(2026, 11, 4))
    assert filings.annual.filing_date == "2026-11-03"
    assert filings.quarterly is None


def test_newer_quarterly_report_is_kept():
    client = client_for({SUBMISSIONS: submissions(page(("10-Q", "2026-10-28"), ("10-K", "2026-07-29")))})
    filings = client.get_filings(COMPANY, today=date(2026, 11, 4))
    assert filings.quarterly.filing_date == "2026-10-28"


def test_amendments_are_not_used_as_the_annual_report():
    client = client_for({SUBMISSIONS: submissions(page(("10-K/A", "2026-03-01"), ("10-K", "2026-02-01")))})
    filings = client.get_filings(COMPANY, today=date(2026, 11, 4))
    assert filings.annual.filing_date == "2026-02-01"


def test_filing_url_uses_undashed_accession_number():
    client = client_for({SUBMISSIONS: submissions(page(("10-K", "2026-02-01")))})
    url = client.get_filings(COMPANY, today=date(2026, 11, 4)).annual.url
    assert url == "https://www.sec.gov/Archives/edgar/data/123/000000000026000000/doc0.htm"


def test_annual_report_is_found_on_older_pages():
    client = client_for({
        SUBMISSIONS: submissions(page(("8-K", "2026-10-01")), [{"name": "older-001.json"}]),
        "older-001.json": page(("10-K", "2026-02-01"), ("10-Q", "2025-11-01")),
    })
    filings = client.get_filings(COMPANY, today=date(2026, 11, 4))
    assert filings.annual.filing_date == "2026-02-01"


def test_predecessor_supplies_the_annual_report(monkeypatch):
    # XOM's ticker moved to a new holding company, and the 10-K is under the old one.
    monkeypatch.setitem(edgar.PREDECESSOR_CIKS, 123, 456)
    client = client_for({
        SUBMISSIONS: submissions(page(("10-Q", "2026-11-02"))),
        "CIK0000000456.json": {"name": "OLD ACME CORP", "filings": {"recent": page(("10-K", "2026-02-18"))}},
    })
    filings = client.get_filings(COMPANY, today=date(2026, 11, 4))
    assert "/data/456/" in filings.annual.url
    assert filings.quarterly.filing_date == "2026-11-02"
    assert any("Old Acme Corp" in warning for warning in filings.warnings)


def test_newly_listed_company_uses_its_quarterly_report_with_a_warning():
    client = client_for({SUBMISSIONS: submissions(page(("10-Q", "2026-08-01")))})
    filings = client.get_filings(COMPANY, today=date(2026, 11, 4))
    assert filings.annual is None
    assert filings.quarterly
    assert "10-Q only" in filings.warnings[0]


def test_foreign_filer_gets_a_specific_message():
    client = client_for({SUBMISSIONS: submissions(page(("20-F", "2026-02-25")))})
    with pytest.raises(UnsupportedFilerError, match="Form 20-F"):
        client.get_filings(COMPANY)


def test_fund_gets_a_specific_message():
    client = client_for({SUBMISSIONS: submissions(page(("N-CSR", "2026-02-25")))})
    with pytest.raises(UnsupportedFilerError, match="fund or ETF"):
        client.get_filings(COMPANY)


def test_old_annual_report_gets_a_warning():
    client = client_for({SUBMISSIONS: submissions(page(("10-K", "2023-01-01")))})
    filings = client.get_filings(COMPANY, today=date(2026, 11, 4))
    assert "no longer be reporting" in filings.warnings[0]


# --- Companies and network behavior ---

TICKERS = {"0": {"cik_str": 123, "ticker": "BRK-B", "title": "Berkshire"}}


def test_dotted_ticker_resolves():
    company = client_for({"company_tickers.json": TICKERS}).resolve_company("brk.b")
    assert (company.ticker, company.cik) == ("BRK-B", 123)


@pytest.mark.parametrize("bad", ["ZZZZ", "not a ticker!", "", "../../etc"])
def test_bad_tickers_are_rejected(bad):
    with pytest.raises(TickerNotFoundError):
        client_for({"company_tickers.json": TICKERS}).resolve_company(bad)


def test_missing_user_agent_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    with pytest.raises(EdgarConfigError, match="SEC_USER_AGENT"):
        EdgarClient()


def test_sec_block_explains_the_likely_fix():
    client = client_for({"company_tickers.json": 403})
    with pytest.raises(EdgarUnavailableError, match="SEC_USER_AGENT"):
        client.resolve_company("AAPL")


def test_outage_uses_saved_copy_and_records_it(monkeypatch):
    client_for({"company_tickers.json": TICKERS}).resolve_company("BRK-B")
    monkeypatch.setattr(cache, "read", lambda ns, key, max_age=None: None if max_age else TICKERS)
    # 500 is retried, so skip the waits between attempts.
    monkeypatch.setattr(EdgarClient._download.retry, "sleep", lambda seconds: None)
    client = client_for({"company_tickers.json": 500})
    assert client.resolve_company("BRK-B").cik == 123
    assert client.used_saved_data


def test_outage_without_saved_copy_is_a_clear_error(monkeypatch):
    monkeypatch.setattr(EdgarClient._download.retry, "sleep", lambda seconds: None)
    with pytest.raises(EdgarUnavailableError, match="can't be reached"):
        client_for({"company_tickers.json": 500}).resolve_company("AAPL")


# --- Financials ---


def fact(end, value, start=None, form="10-K", filed="2026-02-01", fy=2025, accn="a1"):
    return {
        "end": end, "val": value, "form": form, "filed": filed, "fy": fy, "accn": accn,
        **({"start": start} if start else {}),
    }


def facts(**tags):
    gaap = {}
    for tag, entries in tags.items():
        unit = "USD/shares" if tag.startswith("EarningsPerShare") else "USD"
        gaap[tag] = {"units": {unit: entries}}
    return {"facts": {"us-gaap": gaap}}


def test_prior_year_comparatives_are_not_mixed_up_by_fy():
    # Both entries have fy=2025, because `fy` is the filing's year, not the period's.
    result = financials_from_facts(facts(Revenues=[
        fact("2025-12-31", 200, "2025-01-01"),
        fact("2024-12-31", 100, "2024-01-01"),
    ]))
    assert [(y.period_end, y.revenue) for y in result.years] == [
        ("2025-12-31", 200), ("2024-12-31", 100),
    ]


def test_quarterly_and_multi_year_periods_are_excluded():
    # The annual entry comes first, so the later entries would win if they weren't excluded.
    result = financials_from_facts(facts(Revenues=[
        fact("2025-12-31", 200, "2025-01-01"),
        fact("2025-12-31", 50, "2025-10-01"),
        fact("2025-12-31", 900, "2023-01-01"),
        fact("2024-12-31", 25, None),
        fact("2023-12-31", 60, "2023-10-01"),
    ]))
    assert [y.revenue for y in result.years] == [200]


def test_fifty_three_week_year_counts_as_annual():
    result = financials_from_facts(facts(Revenues=[fact("2026-09-26", 300, "2025-09-21")]))
    assert result.years[0].revenue == 300


def test_quarterly_filings_are_excluded():
    result = financials_from_facts(facts(Revenues=[
        fact("2025-12-31", 999, "2025-01-01", form="10-Q"),
    ]))
    assert result.years == []
    assert result.warnings


def test_latest_filed_value_wins_for_restatements_and_splits():
    result = financials_from_facts(facts(EarningsPerShareDiluted=[
        fact("2024-01-28", 11.93, "2023-01-30", filed="2024-02-21"),
        fact("2024-01-28", 1.19, "2023-01-30", filed="2026-02-25"),
    ]))
    assert result.years[0].eps_diluted == 1.19


def test_tag_with_newest_data_wins_over_retired_tag():
    result = financials_from_facts(facts(
        RevenueFromContractWithCustomerExcludingAssessedTax=[fact("2019-12-31", 1, "2019-01-01")],
        Revenues=[fact("2025-12-31", 2, "2025-01-01")],
    ))
    assert result.years[0].revenue == 2


def test_only_recent_years_are_kept_newest_first():
    entries = [fact(f"{y}-12-31", y, f"{y}-01-01") for y in range(2015, 2026)]
    result = financials_from_facts(facts(Revenues=entries))
    assert [y.revenue for y in result.years] == [2025, 2024, 2023, 2022]


def test_missing_metric_gets_a_warning_rather_than_a_guess():
    result = financials_from_facts(facts(Revenues=[fact("2025-12-31", 2, "2025-01-01")]))
    assert result.years[0].net_income is None
    assert any("Net income" in w for w in result.warnings)
    assert any("EPS" in w for w in result.warnings)


def test_company_without_financial_data_gets_a_warning():
    client = client_for({})
    assert client.get_financials(COMPANY).warnings


def test_predecessor_supplies_financials(monkeypatch):
    monkeypatch.setitem(edgar.PREDECESSOR_CIKS, 123, 456)
    client = client_for({
        "CIK0000000123.json": facts(),
        "CIK0000000456.json": facts(Revenues=[fact("2025-12-31", 7, "2025-01-01")]),
    })
    assert client.get_financials(COMPANY).years[0].revenue == 7
