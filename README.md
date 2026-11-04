# Stock Briefing Assistant

An AI prototype that helps wealth advisors get up to speed on a stock quickly. Enter a ticker to get a one-page briefing with a live quote, reported financials and summaries of recent SEC filings, then ask follow-up questions.

Every summary point carries a quote from the filing, and code checks that the quote is really there. Financial figures on the page come straight from the data sources, never from the LLM.

> **Status:** working prototype built for the AI Solution Prototype Challenge (Finance scenario). It isn't production-ready.
>
> **Disclaimer:** information only, not investment advice. The app summarizes facts and doesn't give recommendations.

## Features

- **Live quote:** price, daily change, ranges and market cap, refreshed every 30 seconds while a briefing is on screen.
- **Reported financials:** revenue, net income and diluted EPS for up to 4 fiscal years, from SEC data.
- **Filing summaries:** key points from the latest 10-K, and from the 10-Q when it's newer than the 10-K.
- **Quote verification:** each point is marked as verified or flagged, with its source quote and a link to the filing.
- **Follow-up agent:** answers open questions using tools for quotes, financials and filing sections, and flags figures it can't trace to a tool result.
- **LLM fallback:** moves from Gemini to Groq automatically if Gemini is unavailable, and labels the result.
- **Graceful failures:** clear messages for bad tickers, funds and foreign filers. If the quote or LLM fails, the page keeps what it can and says so.

## Architecture

```
Browser (React + TypeScript)
   |  /api, proxied by Vite in development
   v
FastAPI backend ----> Gemini, with Groq as fallback
   |
   +----> SEC EDGAR (filings, financials)
   +----> Yahoo Finance (quotes)
   +----> Disk cache (saved responses and analyses)
```

A briefing is a fixed pipeline, so every advisor gets the same steps and format:

```
Ticker -> Company lookup -> Quote -> Financials -> Filing sections -> LLM summary -> Quote verification -> Briefing
```

Follow-up questions use a tool-calling agent, because they're too unpredictable for a fixed pipeline. All API keys stay on the server.

### Tech stack

| Layer | Technology |
|---|---|
| Frontend | React 19, TypeScript, Vite, Tailwind CSS, Lucide icons |
| Backend | Python 3.12, FastAPI, Uvicorn, Pydantic |
| LLM | LangChain, Gemini (`gemini-3.5-flash-lite`), Groq (`openai/gpt-oss-120b`) |
| Data | SEC EDGAR via `httpx`, Yahoo Finance via `yfinance`, Beautiful Soup and lxml for parsing |
| Testing | pytest, plus live check scripts |

## Getting started

### Prerequisites

- Python 3.12
- Node.js 20.19 or later, or 22.12 or later
- A [Google AI Studio](https://aistudio.google.com/) API key and a [Groq](https://console.groq.com/) API key

### 1. Set up the backend

```bash
cd backend
```

```bash
conda create -n proto python=3.12 -y
```

```bash
conda activate proto
```

```bash
pip install -r requirements.txt
```

```bash
cp .env.example .env
```

Then fill in `backend/.env` as described under [Configuration](#configuration).

### 2. Start the backend

From `backend/`:

```bash
uvicorn main:app --reload --port 8000
```

### 3. Start the frontend

In a second terminal, from the project root:

```bash
cd frontend
```

```bash
npm ci
```

```bash
npm run dev
```

Open <http://localhost:5173> and try `AAPL`. A first-run briefing has taken up to about 47 seconds, and repeat runs load in about 2 seconds.

## Configuration

Settings live in `backend/.env`. Never commit this file or show it on screen.

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `GEMINI_API_KEY` | Yes, unless failover is forced | None | Main LLM |
| `GROQ_API_KEY` | Recommended | None | Fallback LLM |
| `SEC_USER_AGENT` | Yes | None | Your real name and email. The SEC asks automated clients to identify themselves |
| `GEMINI_MODEL` | No | `gemini-3.5-flash-lite` | Gemini model |
| `GROQ_MODEL` | No | `openai/gpt-oss-120b` | Groq model |
| `FORCE_LLM_FAILOVER` | No | `0` | Set to `1` to skip Gemini and use Groq |

## API

| Method and path | Purpose | Response |
|---|---|---|
| `GET /api/briefings/{ticker}/stream` | Build a briefing. Add `?force_failover=true` to use Groq | Server-sent events: `progress`, then `result` or `failed` |
| `GET /api/quotes/{ticker}` | Get the current quote. Uses no LLM quota | JSON quote, or an error with a `code` and `message` |
| `POST /api/chat` | Answer a follow-up question | JSON answer, tools used, sources, unsupported figures and provider |
| `GET /api/health` | Check the backend's setup. Never includes keys | JSON status and configured providers |

FastAPI also serves interactive API docs at <http://localhost:8000/docs>.

### Examples

```bash
curl http://localhost:8000/api/quotes/AAPL
```

```bash
curl -N http://localhost:8000/api/briefings/AAPL/stream
```

```bash
curl -X POST http://localhost:8000/api/chat -H "Content-Type: application/json" -d '{"ticker": "AAPL", "question": "How did revenue change in the latest fiscal year?"}'
```

A briefing or chat question can use LLM quota. Briefings reuse a saved analysis when one exists for the same filings, but chat answers are never saved.

### Failure codes

| Code | Meaning | Worth retrying? |
|---|---|---|
| `ticker_not_found` | The ticker is invalid or not in the SEC's list | No |
| `unsupported_filer` | A fund, or a foreign filer using Form 20-F or 40-F | No |
| `source_unavailable` | SEC EDGAR can't be reached and no saved copy exists | Yes |
| `llm_unavailable` | No LLM could answer | Yes |
| `quote_unavailable` | No live or saved quote exists | Yes |
| `configuration_error` | A key or model name was rejected | No |
| `internal_error` | An unexpected error, with details in the server log only | Yes |

## Testing

All commands run from `backend/`, except the frontend build.

| Command | What it checks | Uses LLM quota? |
|---|---|---|
| `python -m pytest` | Unit tests, with LLMs and network replaced by fakes | No |
| `python check_data.py` | Live SEC and quote data across real companies | No |
| `python evals.py` | Measures verification and section extraction, and writes `eval_results.md` | Only for analyses not yet saved |
| `python check_llm.py` | Both providers: replies, structured output, tool calls and failover | Yes, a small amount |
| `python check_briefing.py` | Real briefings on both providers. `--fresh` ignores saved analyses | Only for analyses not yet saved |
| `python check_api.py` | Starts the real server and streams real briefings | Only for analyses not yet saved |
| `python check_agent.py` | Real follow-up questions on both providers | Yes |
| `npm run build` (in `frontend/`) | Type-checks and builds the frontend | No |

There are no automated frontend tests. The UI has been checked by hand in a real browser.

## Evaluation results

From [`backend/eval_results.md`](backend/eval_results.md), mostly one run per company and LLM:

| Provider | Companies | Quotes verified | Range by company | Required sections found | Median tokens (in + out) | Median LLM time |
|---|---|---|---|---|---|---|
| Gemini (full) | 10 | 150 of 158 (95%) | 85% to 100% | 30 of 30 | 30,467 + 1,667 | 18.6 s |
| Groq (reduced) | 3 | 31 of 34 (91%) | 85% to 100% | 9 of 9 | 4,914 + 1,317 | 3.6 s |

How to read these:

- **Small sample:** the prompt was tuned using these same companies, so the rates may be flattering. One company not used for tuning, Disney, verified 19 of 19.
- **What's measured:** each quote exists in the filings and contains the claim's amounts. Whether each claim is a fair reading of its quote isn't measured.

## Key design decisions

| Decision | Why | Tradeoff |
|---|---|---|
| Fixed pipeline for briefings, agent for follow-ups | Consistent, testable briefings, with flexibility where questions are unpredictable | Follow-ups are more variable |
| The LLM never supplies displayed financial figures | Those numbers mustn't depend on a model | Summaries can only cite figures in the text they're given |
| Each claim needs a quote that code verifies | A simple, deterministic check an advisor can see | Doesn't prove the claim is a fair reading |
| Flagged claims stay visible | Advisors can judge them, and nothing is silently dropped | Some correct claims get flagged, because the check is strict |
| A custom fallback wrapper instead of LangChain's `with_fallbacks` | Groq needs a smaller request, and the UI needs to know who answered | A little more code to maintain |
| Shorter "reduced" briefing on Groq | Groq's listed limit is 8,000 tokens per minute, far below a full briefing's request | Covers fewer points, and is labeled |
| React and FastAPI rather than a Python-only UI | Keeps keys on the server, and the backend can serve other clients | Takes longer to build |

## Known limitations

- **Claims and chat:** summary claims aren't checked for fair reading. Follow-up answers aren't quote-checked, and the figure flag can't catch a real figure attached to the wrong year.
- **Coverage:** funds and foreign filers using Form 20-F or 40-F aren't supported. Section extraction has only been tested on a small number of companies, and some filings' sections are found by name and show a warning.
- **Long filings:** only part of a long section is read, and the page says so.
- **Reorganized companies:** XOM's history is linked through a hand-written table. Other reorganized or newly listed companies get a labeled briefing from their 10-Q alone.
- **LLM availability:** free tiers can overload or hit rate limits, and Gemini did so repeatedly during testing. The latest Groq rate-limit fix has unit tests but hasn't been proven in a live run.
- **Market data:** Yahoo Finance is unofficial and may be delayed.
- **Advice filter:** it matches set phrases, so it's a backstop for the prompt rather than a compliance control.
- **Not included:** authentication, client portfolio data, the trend chart and frontend tests.

## Path to production

- Licensed market data
- A paid LLM tier, or a gateway such as Portkey for keys, routing and logging
- A human-reviewed evaluation set, including whether claims are a fair reading
- Compliance review
- Single sign-on, access controls and audit logs
- CRM or portfolio system integration
- A pilot with advisors and agreed success measures

## Project structure

```
.
├── README.md
├── plan.md                    Development plan, results and decisions
├── Financial Data Summarizer_deck.pptx  Pitch slide
├── backend/
│   ├── main.py                API routes
│   ├── briefing.py            Briefing pipeline, prompts and quote verification
│   ├── agent.py               Follow-up agent and its tools
│   ├── llm.py                 Gemini and Groq setup, fallback and retries
│   ├── edgar.py               SEC filings, section extraction and financials
│   ├── quotes.py              Quotes, with fallbacks
│   ├── schemas.py             Shared data models
│   ├── cache.py               Disk cache
│   ├── evals.py               Evaluation script
│   ├── eval_results.md        Latest evaluation results
│   ├── check_*.py             Live checks
│   ├── tests/                 Unit tests
│   └── .env.example           Settings template
└── frontend/
    └── src/
        ├── App.tsx            Page and briefing states
        ├── api/               API client, types and live quote refresh
        ├── components/        Page components
        └── lib/format.ts      Number and date formatting
```

## Data sources

- [SEC EDGAR](https://www.sec.gov/edgar): filings and financial data. Requests are limited to under 10 per second, as the SEC asks.
- [Yahoo Finance](https://finance.yahoo.com/) via [`yfinance`](https://github.com/ranaroussi/yfinance): quotes, for prototype use only.
