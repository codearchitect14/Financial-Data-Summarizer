# Evaluation results

Generated 2026-11-04T19:14:45+00:00. One run per ticker and provider, so treat this as a small sample.

| Provider | Tickers | Quotes verified | Range by ticker | Required sections found | Median tokens (in + out) | Median LLM time |
|---|---|---|---|---|---|---|
| Gemini (full) | 10 | 150 of 158 (95%) | 85% to 100% | 30 of 30 | 30,467 + 1,667 | 18.6 s |
| Groq (reduced) | 3 | 31 of 34 (91%) | 85% to 100% | 9 of 9 | 4,914 + 1,317 | 3.6 s |

| Ticker | Provider | Verified | Found by name, not heading | Years | LLM time |
|---|---|---|---|---|---|
| AAPL | gemini | 9 of 10 | None | 4 | 22.26 s |
| MSFT | gemini | 19 of 20 | None | 4 | 15.76 s |
| NVDA | gemini | 17 of 20 | None | 4 | 15.26 s |
| JPM | gemini | 16 of 17 | mdna, quarterly_mdna | 4 | 14.24 s |
| XOM | gemini | 14 of 14 | mdna | 4 | 17.5 s |
| TSLA | gemini | 16 of 16 | None | 4 | 20.5 s |
| WMT | gemini | 16 of 16 | None | 4 | 19.71 s |
| PFE | gemini | 11 of 12 | None | 4 | 20.18 s |
| GOOGL | gemini | 10 of 10 | None | 4 | 14.93 s |
| ORCL | gemini | 22 of 23 | None | 4 | 26.15 s |
| AAPL | groq | 8 of 9 | None | 4 | 2.26 s |
| JPM | groq | 12 of 12 | mdna, quarterly_mdna | 4 | 3.57 s |
| WMT | groq | 11 of 13 | None | 4 | 4.52 s |

| Rejected ticker | Passed | Message |
|---|---|---|
| ASML | Yes | ASML HOLDING NV (ASML) is a foreign filer that reports on Form 20-F. This prototype covers companies that file a 10-K. |
| SPY | Yes | SPDR S&P 500 ETF TRUST (SPY) has no 10-K on file. It may be a fund or ETF, which this prototype doesn't cover. |
| ZZZZZ | Yes | "ZZZZZ" isn't in the SEC's list of company tickers. Check the ticker. Funds such as many ETFs aren't listed. |

Measured: each quote is in the filings and contains the claim's amounts. Not measured: whether each claim is a fair reading of its quote.
