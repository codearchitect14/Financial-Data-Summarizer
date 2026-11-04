# Plan: Stock Briefing Assistant for Wealth Advisors (Finance)

## 1. The brief

**Client:** a wealth management firm.
**User:** an advisor who needs to get up to speed on a stock quickly, for example before a client call.
**Required:** enter a stock, get current quote data and a summary of key information from recent SEC filings.

**Product in one line:** enter a ticker and get a one-page, source-linked briefing, then ask follow-up questions. The target is under a minute per briefing, to be confirmed by measurement in Phase 7.

### What we must deliver

| Deliverable | Requirement | Recommended time |
|---|---|---|
| Working prototype | Demonstrable live; not production-ready; any interface | 120 min |
| One slide | Pitch to the panel as client stakeholders | 10 min |
| Live interview | Present the slide, demo, answer stakeholder questions | 20 min |

### What the panel is judging, and how we answer it

| Criterion | How this plan answers it |
|---|---|
| Solution design | A fixed pipeline for the briefing, and an agent only for open-ended questions |
| Technical execution | Live data, real filings, and a working demo on a ticker the panel chooses |
| Communication | Decisions narrated during the build (section 8) and a clear business story |
| Working under constraints | Pre-agreed cut lines (section 6) and stated tradeoffs (section 9) |
| Business impact | Less preparation time per stock, and output an advisor can check and trust |

### Rules to follow

- Use industry-accepted tools. Nothing completely custom-built.
- The session is recorded and the hiring manager reviews the transcript, so talk through decisions as you go.
- Use open source packages: Python for the backend and React for the front end, with Gemini as the main LLM and Groq as the fallback (section 4).
- Questions about Perficient or the role go to the recruiter, not the interviewer.

### Open questions: ask the recruiter before the interview

1. **Time limit:** the recommended times add up to 150 minutes (120 + 10 + 20), which equals the "up to 2.5 hours" in the instructions. Confirm whether the 2.5 hours includes the 20-minute interview. This plan assumes it does, so it budgets 130 minutes for the build and slide.
2. **LLM keys:** the challenge provides Portkey access and says its gateway is what the firm uses, but it does not say you must use it. Confirm that your own Gemini and Groq keys are acceptable. If Portkey turns out to be required, it can be added as another provider in `llm.py` (section 4).

## 2. Solution design

```
Ticker
  |
  +--> Resolve ticker to CIK (SEC ticker map)
  |
  +--> Quote (yfinance, then backups) ------------+
  +--> Financials (EDGAR company facts) ----------+--> Numbers shown as-is,
  |                                               |    never written by the LLM
  +--> Latest 10-K, 10-Q (EDGAR submissions)      |
         |                                        |
         +--> Extract key sections                |
         +--> LLM summary with supporting quotes  |
         +--> Check each quote against the filing |
                    |                             |
                    +--------> Briefing page <----+
                                    |
                                    +--> Follow-up Q&A agent with tools
```

### Key design decisions

| Decision | Choice | Why | Tradeoff |
|---|---|---|---|
| Briefing flow | Fixed pipeline, not an agent | Every advisor gets the same steps and format, and it is faster, cheaper and easier to test | Less flexible |
| Follow-up questions | Tool-calling agent | Questions are unpredictable, so this is where an agent adds value | More variable; needs a step limit |
| Numbers | Taken from APIs and shown directly | Financial figures must not depend on an LLM | Narrative can only cite figures it was given |
| Trust | Each claim needs a supporting quote, and code checks the quote is in the filing | A simple, deterministic check that catches invented support | Checks that the quote exists, not that the claim is a fair reading of it |
| Filing input | Extract sections rather than send the whole filing | Apple's 10-K is about 58k tokens in total; its MD&A is only about 4k | Section extraction can fail on unusual layouts |
| Stack | React front end, FastAPI backend, LangChain (section 4) | Looks and behaves like a real client product, and keeps API keys on the server | Takes longer than a Python-only UI, so the phases are tighter |
| LLM providers | Gemini first, Groq on failure | The demo survives a rate limit or outage on one provider | Output quality can differ, and Groq's lower limits need a reduced briefing |
| Compliance | Summarizes facts; no buy or sell recommendations | Advisors remain responsible for advice | Less "decision support" in the prototype |

### Briefing contents

1. **Snapshot:** price, daily change, day range, 52-week range, and an as-of time.
2. **Financial trend:** revenue, net income and EPS for recent fiscal years, from company facts.
3. **Business summary:** what the company does and how it makes money.
4. **Management's view:** key points from MD&A.
5. **Key risks:** the most material items from Risk Factors.
6. **Recent quarter:** key points from the latest 10-Q, only if it was filed after the latest 10-K. Otherwise the 10-K is the newest source, and the page says so.
7. **Questions a client may ask:** prompts for the advisor, not recommendations.
8. **Sources:** link to each filing, with supporting quotes and a verified or unverified status.

## 3. Data sources

All tested live on 2026-11-04, except where noted.

| Need | Source | Tested result |
|---|---|---|
| Ticker to CIK | `https://www.sec.gov/files/company_tickers.json` | 200 with a contact-style `User-Agent`; 403 without one |
| Filing list | `https://data.sec.gov/submissions/CIK##########.json` | 200 |
| Financials | `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json` | 200 (3.9 MB for Apple) |
| Filing text | `https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}` | 200 (Apple 10-K: 1.65 MB, 1.2 s) |
| Quote | `yfinance` package, using `.info` | Works; unofficial, can be rate-limited. Don't use `fast_info`: its previous close was wrong for AAPL (330.28 versus 331.90) and it has no as-of time |
| Backup quote | `https://query1.finance.yahoo.com/v8/finance/chart/{ticker}` | 200; also Yahoo, so it won't help if Yahoo itself is down |
| Last resort quote | Last saved quote, labeled with its as-of time | Built in Phase 2 |

### Quote freshness policy

- Do not call Yahoo data "live" or "real-time." A recent timestamp proves recency, not the feed's delivery guarantee. Label it **"Latest available from Yahoo Finance"** and show the source-provided market timestamp.
- Keep three separate fields in the quote contract and UI: the source's delivery guarantee, the age of the market timestamp, and whether the value came from the local cache.
- While the relevant exchange is open, accept a quote as recent only when its market timestamp is no more than 15 minutes old. Otherwise suppress the price, daily change and short-term price commentary and state that current market data is unavailable.
- While the exchange is closed, a verified latest regular-session close may remain visible through overnight hours, weekends and exchange holidays, labeled **"Market closed - previous close"** with its timestamp. Do not relabel a cached intraday observation as a closing price.
- Suppress any cached intraday quote from an earlier trading session. Continue the filing-based briefing because its source dates and validity are independent of quote availability.
- The prototype should use the security's exchange and timezone when applying this rule. Production should use an exchange calendar plus a licensed provider's official delay and entitlement metadata.

### What the tests mean for the build

- **User-Agent:** send one on every SEC request, using your real name and email from `.env`. The test used a placeholder address, but the SEC asks for real contact details.
- **Rate limit:** the SEC's published limit is 10 requests per second. This app stays well under it, but cache responses anyway.
- **Finding filings:** the `recent` list can miss older filings on very active filers, so also search the older pages under `filings.files`.
- **Reorganized companies:** the XOM ticker now belongs to ExxonMobil Holdings Corp, a new registrant with a 10-Q but no 10-K. The 10-K and financial history are under the old Exxon Mobil Corp. A small `PREDECESSOR_CIKS` table handles known cases. Any other company with a 10-Q but no 10-K, including new listings, gets a labeled briefing from the 10-Q alone.
- **Choosing the 10-Q:** a 10-Q can be older than the latest 10-K. Apple's 10-K is from 2026-11-03 and its 10-Q from 2026-07-31. Only use a 10-Q filed after the 10-K.
- **Section extraction:** headings such as "Item 1A" appear in the table of contents, in the body and in cross-references. Taking the first or last match fails: the last match found no section on NVDA, JPM and BAC. **Find every match, ignore mentions such as "see Item 1A", measure the text up to the next real item heading, and keep the longest.**
- **When the longest match is too short:** treat under about 2,000 characters as not found. JPM, BAC and XOM have no usable "Item 7" heading above their MD&A, so fall back to searching for the section's name, stopping at Item 7A or the auditor's report. Show a warning on any section found this way, or if it can't be found at all.
- **Short 10-Q risk sections:** "no material changes" is a valid answer, and many 10-Qs have no such section, so neither is treated as a failure.
- **Filing size:** bank filings are very large (JPM is about 294k tokens and BAC about 220k), and sections can be too (BAC's Item 7 is about 112k tokens). Always cap the section text sent to the LLM.
- **Financial tags:** company facts labels vary by company, for example `Revenues`, `RevenueFromContractWithCustomerExcludingAssessedTax`, and for banks `RevenuesNetOfInterestExpense`. Use an ordered fallback list.
- **Financial periods:** the `fy` field is the year of the filing, not the period measured, so a filing's prior-year comparisons share its `fy`. Select annual values by each entry's `start` and `end` dates, and show the latest filed value for each period.
- **Ticker formats:** the SEC map uses `BRK-B`, not `BRK.B`. Convert to uppercase and replace dots with hyphens.
- **Edge cases to handle with a clear message:** invalid tickers, ETFs (SPY is in the map but has no 10-K, and QQQ is not in the map) and foreign filers (ASML files a 20-F).

## 4. Tech stack and project structure

### Tech stack

All packages are open source. Gemini and Groq are hosted services that use your API keys. The backend versions are installed in the `proto` conda environment. The frontend versions resolved in an npm dry run on 2026-11-04 but are not installed yet. Pin them in `requirements.txt` and `package-lock.json`.

**Frontend**

| Layer | Choice | Version | License | Used for |
|---|---|---|---|---|
| Framework | `react`, `react-dom` | 19.3.1 | MIT | User interface |
| Language | `typescript` | 7.0.2 | Apache-2.0 | Typed components and API data |
| Build tool | `vite`, `@vitejs/plugin-react` | 8.3.5, 6.2.1 | MIT | Dev server, API proxy, builds |
| Styling | `tailwindcss`, `@tailwindcss/vite` | 4.3.4 | MIT | Consistent spacing, type and color |
| Components | `shadcn` (shadcn/ui) | 4.23.0 | MIT | Accessible cards, badges, tables, drawers |
| Charts | `recharts` | 3.10.1 | MIT | Financial trend chart |
| Icons | `lucide-react` | 1.68.0 | ISC | Interface icons |

**Backend**

| Layer | Choice | Version | License | Used for |
|---|---|---|---|---|
| Language | Python | 3.12 | PSF | All backend code |
| API | `fastapi`, `uvicorn` | 0.162.0, 0.54.0 | MIT, BSD-3-Clause | REST and streaming endpoints |
| LLM framework | `langchain` | 1.4.9 | MIT | Agent, shared model interface |
| Main LLM | `langchain-google-genai` | 4.4.2 | MIT | Connects to Gemini |
| Fallback LLM | `langchain-groq` | 1.1.3 | MIT | Connects to Groq |
| Schemas | `pydantic` | 2.14.2 | MIT | Briefing output structure |
| HTTP | `httpx` | 0.28.1 | BSD-3-Clause | SEC EDGAR and backup quote requests |
| Retries | `tenacity` | 9.1.4 | Apache-2.0 | Retrying failed data requests |
| Quotes | `yfinance` | 1.8.0 | Apache-2.0 | Current quote data |
| Filing parsing | `beautifulsoup4`, `lxml` | 4.15.0, 6.1.3 | MIT, BSD-3-Clause | Turning filing HTML into clean text |
| Config | `python-dotenv` | 1.2.4 | BSD-3-Clause | Loading keys from `.env` |
| Tests | `pytest` | 9.2.0 | MIT | Parser and verification tests |
| Tracing (optional) | Langfuse or Arize Phoenix | Latest | Open source | Only if ahead of schedule |

### LLM setup

| Role | Provider | Model | Why |
|---|---|---|---|
| Main | Gemini | `gemini-3.5-flash-lite` | Labeled stable and recommended for new projects in Google's docs; fast and low cost |
| Upgrade option | Gemini | `gemini-3.8-flash` | Also recommended, but labeled "New" rather than stable. Try it if summaries are weak |
| Fallback | Groq | `openai/gpt-oss-120b` | Production model with tool use and strict structured output |

Keep model names in `.env` so they can change without a code change.

```
GEMINI_API_KEY=
GROQ_API_KEY=
GEMINI_MODEL=gemini-3.5-flash-lite
GROQ_MODEL=openai/gpt-oss-120b
SEC_USER_AGENT=Your Name your.email@example.com
```

**How the fallback works**

- **Use a small custom wrapper, not LangChain's `with_fallbacks`.** `with_fallbacks` sends the same input to both models and doesn't report which one answered. Groq needs a smaller input and the UI needs a provider label, so `llm.py` provides `call_with_fallback(call)`, where `call` receives the provider and builds the right request for it.
- **What each call returns:** the value, provider, model, whether it fell back and why, tokens used and time taken. The token count also answers the cost question in section 8.
- **When it fails over:** rate limits (429), request timeouts (408), server errors (5xx), connection failures, timeouts, or invalid structured output from Gemini.
- **When it does not:** invalid keys, permissions, unknown models or malformed requests (400, 401, 403, 404). These are setup errors that Groq shouldn't hide, so they stop with a clear message.
- **Fail over quickly:** no automatic retries on Gemini, because its client defaults to 6. The timeout is 30 seconds, or 60 for the larger briefing request.
- **Follow-up agent:** if Gemini fails, rerun the whole question on Groq rather than switching midway. Tool call history may not carry cleanly between providers.
- **Be open about it:** show which provider produced each briefing in the UI and in the logs.
- **Test switch:** a `FORCE_LLM_FAILOVER=1` setting forces Groq, so the fallback can be tested and shown on demand.

**Reduced briefing on Groq**

Groq's docs list 8K tokens per minute for `openai/gpt-oss-120b` on the Developer plan, and free plan limits may be lower. A full briefing won't fit in that, so the fallback uses a smaller version. Both providers get one combined request, which saves calls against rate limits and means a briefing never mixes providers. Only the amount of filing text differs:

- Gemini: up to 150k characters (about 38k tokens), 3 to 5 points per section.
- Groq: up to 16k characters (about 4k tokens), at most 2k tokens of output, 2 or 3 points per section. Groq counts input plus the full output allowance up front, and at 20k characters a request asked for 7,033 of the 8,000 tokens per minute, so any other use that minute blocked it. On a rate limit it now waits 8 seconds and retries once. This change has unit tests but hasn't been proven live.
- `read_filing_section` capped at about 1.5k tokens, with at most 2 tool steps, when the agent runs on Groq. Each step resends earlier results, so larger results would pass the limit within a single question.
- A visible "Reduced briefing" label.
- A clear "try again shortly" message if a follow-up comes too soon after a reduced briefing, because they share the same per-minute limit.

Gemini's docs do not publish free tier figures, so read your actual limits in AI Studio. Run calls one at a time unless those limits clearly allow parallel calls.

### Application architecture

```
Browser (React + TypeScript)
   |  /api requests, proxied by Vite in development
   v
FastAPI backend ---> Gemini, with Groq as fallback
   |
   +---> SEC EDGAR, Yahoo quotes, cache/
```

All API keys stay in the backend, and the browser never sees them. The Vite proxy also means no CORS setup is needed.

### API contract

| Endpoint | Purpose | Response |
|---|---|---|
| `GET /api/briefings/{ticker}/stream` | Generate a briefing | Server-sent events: `progress` (`step`, `message`) for each step, then `result` (the briefing) or `failed` (`code`, `message`, `retryable`) |
| `POST /api/chat` | Answer a follow-up question | Request: ticker, question, earlier messages. JSON response: answer, tools used, sources, unsupported figures, provider |
| `GET /api/quotes/{ticker}` | Refresh the quote every 30 s while a briefing is on screen, using no LLM quota | JSON: the quote |
| `GET /api/health` | Check that the backend is ready | JSON: status and configured providers, never keys |

- **Streaming:** use FastAPI's `StreamingResponse` with `text/event-stream`, and `EventSource` in the browser. This shows real progress during a wait of up to a minute, with no extra packages.
- **Avoid accidental reruns:** `EventSource` reconnects automatically when a stream ends, which would generate and pay for the briefing again. Call `close()` as soon as `result` or `failed` arrives. Don't name our event `error`, because that clashes with the browser's built-in connection event.
- **Types:** keep `src/api/types.ts` in line with the Pydantic models. Generating them from the API schema can come later.
- **Blocking work:** run slow data and LLM calls in a thread so that one request doesn't freeze the server.

### Frontend design

**Layout (desktop first, as the demo is on a laptop; panels stack on narrower screens)**

```
+------------------------------------------------------------+
| Product name         [ Ticker search ]        Provider tag |
+---------------------------------------+--------------------+
| Company, price, change, as-of time    | Ask about this     |
| Key metric cards                      | company            |
| Financial trend chart and table       |                    |
| Tabs: Business, Management's view,    | Chat messages      |
|       Risks, Recent quarter           | Tools used         |
| Claims with verified or unverified    |                    |
| badges (click to open source drawer)  | [ Question box ]   |
+---------------------------------------+--------------------+
| Information only, not investment advice. Sources: SEC, Yahoo |
+------------------------------------------------------------+
```

**Components**

| Component | Purpose |
|---|---|
| `TickerSearch` | Input, validation, suggested tickers |
| `ProgressSteps` | Live steps: quote, filings, analysis, verification |
| `QuoteHeader`, `MetricCards` | Price, change, ranges, as-of time |
| `FinancialTrend` | Revenue, net income and EPS chart, with a table of exact figures |
| `BriefingTabs`, `ClaimItem` | Summary sections with verification status |
| `SourceDrawer` | Supporting quote and link to the original filing |
| `ChatPanel` | Follow-up questions and tools used |
| `ProviderBadge`, `ReducedBanner` | Which LLM answered, and whether the briefing is reduced |
| `Disclaimer` | Information-only notice |

**What makes it look professional**

- **A restrained visual style:** one neutral palette and one accent color, one type scale, and consistent spacing from the shared components. Keep it calm, like a financial tool, with no decorative effects.
- **Numbers done properly:** aligned digits (`tabular-nums`), consistent currency and percentage formats, and every figure labeled with its period.
- **Red and green with a second signal:** price changes also show a sign or arrow, so meaning never depends on color alone.
- **All states designed:** loading shows skeletons and live steps. Errors explain what happened and offer a retry. Saved data is clearly labeled with its age.
- **Accessibility:** full keyboard use, visible focus, labeled inputs and sufficient contrast. shadcn/ui handles much of this.
- **Safe rendering:** show LLM output as plain text, and never insert it as raw HTML.

**Deliberately left out:** login, dark mode, saved history, mobile polish and frontend automated tests. The challenge rewards problem-solving over polish, and the rehearsal covers the UI by hand.

### Project structure

```
Project/
  backend/
    main.py        FastAPI routes (replaces the empty main.py in Project/)
    schemas.py     Pydantic models for briefings and chat
    llm.py         Gemini and Groq setup, fallback logic, provider label
    check_llm.py   Live checks of both providers using your keys
    check_data.py  Live checks of EDGAR and quotes across real companies
    check_briefing.py  Live checks of real briefings on both providers
    check_api.py   Starts the real server and streams real briefings
    check_agent.py Live checks of real questions on both providers
    pytest.ini     Test configuration
    cache.py       Disk cache for repeat runs and source outages
    edgar.py       Ticker lookup, filing list, section extraction, financials
    quotes.py      yfinance, backup endpoint, last-saved fallback
    briefing.py    Summary prompts, quote verification, progress events
    agent.py       Follow-up Q&A tools and agent
    evals.py       Checks across several tickers
    tests/         pytest tests for fallback, section extraction and quote verification
    cache/         Saved responses for demo fallback
    .env           API keys and settings (never commit or show on screen)
    .env.example   Template for .env, with no real values
    requirements.txt
  .gitignore       Excludes .env, cache and build output
  frontend/
    src/
      api/         API client, EventSource wrapper, types.ts
      components/  Components listed above
      components/ui/  Generated shadcn/ui components
      lib/format.ts   Currency, percentage and date formatting
      App.tsx
    vite.config.ts    Includes the /api proxy to port 8000
    package.json
```

Agent tools: `get_quote`, `get_financials(metric)`, `read_filing_section(form, item)`.

## 5. Phase-wise development plan (130 minutes)

Each phase ends with a test. Don't start the next phase until it passes, unless you're using a cut line from section 6.

| Phase | Time | Output |
|---|---|---|
| 1. Setup and LLM layer | 0-15 | Both providers working, including fallback |
| 2. Data layer | 15-35 | Quote, financials and filing sections for any ticker |
| 3. Briefing engine | 35-55 | Verified structured briefing |
| 4. API layer | 55-65 | FastAPI streaming a full briefing |
| 5. React front end | 65-90 | Complete core demo in the browser |
| 6. Follow-up agent | 90-108 | Questions answered using tools, in the chat panel |
| 7. Hardening and evals | 108-120 | Measured results, edge cases, rehearsal |
| 8. Slide | 120-130 | One finished slide |
| Live interview | 130-150 | Slide, demo, questions |

**Run it with two terminals:** `uvicorn main:app --reload --port 8000` from `backend/`, and `npm run dev` from `frontend/`.

### Phase 1: Setup and LLM layer (0-15 min)

**Packages:** `langchain`, `langchain-google-genai`, `langchain-groq`, `pydantic`, `python-dotenv`, `pytest`

1. Read the brief aloud and state the user, scope and approach.
2. Create `.env`, `.env.example`, `.gitignore` and `requirements.txt`.
3. Build `llm.py` with both providers, `call_with_fallback` and the `FORCE_LLM_FAILOVER` switch.
4. Add `pytest` tests for the fallback rules, which need no keys.
5. Run `check_llm.py`: a plain reply, a structured output and a full tool call round trip on **each** provider.

**Passes when:** the tests pass, all six live checks succeed, and both the forced failover and a real Gemini timeout return an answer labeled Groq.

**Status:** passed on 2026-11-04. `check_llm.py` passed 8 of 8 live checks, including a real Gemini timeout moving to Groq. Later runs sometimes passed 7 of 8 because of temporary Gemini 503, 504 or timeout errors, as covered in section 9.

`gemini-3.5-flash-lite` ignores the `temperature` setting, so its output can't be pinned that way. Quote verification and the fixed schema are what keep results checkable.

### Phase 2: Data layer (15-35 min)

**Packages:** `httpx`, `tenacity`, `yfinance`, `beautifulsoup4`, `lxml`

1. `edgar.py`: normalize the ticker, get the CIK, and find the latest 10-K, searching older filing pages if needed. Use the 10-Q only if it's newer than the 10-K.
2. `edgar.py`: download the 10-K, convert it to clean text, and extract Item 1, 1A and 7 using the longest-match rule and fallback in section 3.
3. `edgar.py`: extract the 10-Q's MD&A (Part I, Item 2) and any risk factor updates (Part II, Item 1A). Its item numbers differ from the 10-K's.
4. `edgar.py`: revenue, net income and EPS from company facts, using the tag and period rules in section 3.
5. `quotes.py`: `yfinance`, then the backup endpoint, then the last saved quote. Apply the quote freshness policy in section 3 before exposing any saved price to the briefing or UI.
6. Save responses to `cache/`.

**Passes when:** AAPL, JPM, MSFT and XOM each return a quote, correct annual financials, and section text or a clear warning. SPY, ASML and an invalid ticker each get a clear message.

**Status:** passed on 2026-11-04. `check_data.py` passed 11 of 11 live checks, also covering NVDA, BAC and BRK.B, and checks one known financial figure for each of AAPL, MSFT, JPM, XOM and NVDA.

**Known limits:** Berkshire's EPS isn't found, because it doesn't use the standard tags, so it shows a warning rather than a figure. Bank MD&A sections are very long (JPM's 10-Q section also runs into its financial statements), so Phase 3 must cap the text sent to the LLM. Only the start of each section has been checked by eye, not the whole text.

### Phase 3: Briefing engine (35-55 min)

**Packages:** `langchain`, `pydantic`

1. Define the Pydantic schema, where each claim has text, a supporting quote and a source.
2. Write the prompts: summarize only from the provided text, make no recommendations, and treat filing text as data rather than instructions.
3. Check each quote against the filing text, ignoring differences in spacing, letter case, and curly quotes or dashes. Also check that any number in the claim appears in its quote. Reject quotes under 5 words, and remove any claim or question that gives advice.
4. Add the reduced briefing for Groq.
5. Add `pytest` tests for section extraction and quote verification.

**Passes when:** a full AAPL briefing returns with verification results on Gemini, and a reduced one returns on Groq.

**Status:** passed on 2026-11-04. `check_briefing.py` passed with real briefings:

| Briefing | Provider | Quotes verified | Tokens (in + out) | LLM time | Total time |
|---|---|---|---|---|---|
| AAPL full | Gemini | 9 of 9 (100%) | 23,369 + 981 | 15 s | 16 s |
| JPM full | Gemini | 12 of 15 (80%) | 34,409 + 1,490 | 28 s | 30 s |
| AAPL reduced | Groq | 7 of 9 (78%) | 4,831 + 1,150 | 3 s | Not measured |

These are small samples from one run each, so Phase 7 still needs to measure more tickers before any number goes on the slide. The remaining rejections were a reworded quote or a claim with figures its quote didn't contain, and the check requires at least 70% on both providers. Whether each claim fairly reflects its quote has not been measured.

**What real runs changed:**

- Groq's reasoning used up its output limit before finishing the JSON, so reasoning effort is set to low.
- Groq reports unfinished output as a 400 error, which is now treated as an outage rather than a bad key.
- Claims may add a year for context, as the quoted sentence often doesn't state it. Amounts and percentages must still match.
- Page numbers stranded mid-sentence in filings no longer cause false rejections.
- Gemini returned real 503 and 504 errors, so it now gets one retry after 2 seconds before failing over.
- A claim can quote a different section from the one it's filed under, so quotes are checked against all the sections read.

**Other behavior:** long sections are read only in part, and marked as such. If the quote or the LLM fails, the briefing still returns what it can with a warning. Analyses are saved per filing, so repeat runs cost nothing.

### Phase 4: API layer (55-65 min)

**Packages:** `fastapi`, `uvicorn`

1. Build the three endpoints in the API contract, starting with `/api/briefings/{ticker}/stream` and `/api/health`.
2. Send `progress` events from the briefing steps, then `result` or `failed`.
3. Return clear error types for a bad ticker, no 10-K, and both LLM providers failing.

**Passes when:** `curl -N` shows live progress and then a complete briefing.

**Status:** passed on 2026-11-04. `curl -N` on MSFT showed the analysis step at 2 s and the result at 26 s, so events do arrive live. `check_api.py` passed 9 of 9 live checks, and the API has unit tests too. `?force_failover=true` on the stream shows the Groq path without a restart.

### Review of Phases 1 to 4 (2026-11-04)

Every step in Phases 1 to 4 is done. Real briefings so far, one run each:

| Provider | Tickers | Quotes verified | First-run total time |
|---|---|---|---|
| Gemini | AAPL, JPM, NVDA, XOM, MSFT | 62 of 69 (90%) | 16 to 30 s |
| Groq (reduced) | AAPL, JPM | 15 of 21 (71%) | About 5 s for JPM |

**Open items, none blocking:**

- **Phase 5:** show the `truncated` flag, as long sections are read only in part. On MSFT, all five sections were. Start the stream on submit, not in a React effect, because Strict Mode would run it twice in development and pay for it twice.
- **Source links:** a claim can quote a different section from the one it's filed under, so its link could point to the other filing when a briefing uses both a 10-K and 10-Q. The page should say the quote comes from "the filings read".
- **Not tested live:** searching older filing pages, because no tested company needed it. It has unit tests only.
- **JPM on Groq:** 8 of 12 verified (67%), below the 70% that `check_briefing.py` requires, though that script only runs AAPL on Groq. Reduced briefings are labeled and flagged.
- **Gemini reliability:** still the main demo risk (section 9).
- **Still open for you (section 10):** confirm with the recruiter that your own keys are acceptable, and whether code built before the session can be used.

### Plan for the last 30 minutes

Phase 4 used part of this time. Spend what's left on what the panel will see, and test only by using the real app.

| Budget | Work | Testing |
|---|---|---|
| About 13 min | Phase 5, core page only | One real ticker and one bad ticker in the browser |
| About 6 min | Phase 6, agent and chat panel | The one question in Phase 6's pass condition |
| About 3 min | Final check | `pytest`, then run the demo tickers once so their analyses are saved |
| About 3 min | Slide | Use the review table above, labeled as a small sample |

**Cut now:** trend chart (keep the table), tabs (use one scrolling page), source drawer (show quotes inline), `evals.py` (use the review table), frontend tests.

**If the core page isn't working with 12 minutes left:** skip the agent's UI, and explain its design using the tested tool round trip.

### Phase 5: React front end (65-90 min)

**Packages:** `react`, `typescript`, `vite`, `tailwindcss`, `shadcn`, `recharts`, `lucide-react`

1. **65-70:** Scaffold with Vite, set up Tailwind and shadcn/ui, and add the `/api` proxy.
2. **70-75:** Add `types.ts`, the API client, `format.ts` and the page layout.
3. **75-85:** Build `TickerSearch`, `ProgressSteps`, `QuoteHeader`, `MetricCards`, `BriefingTabs`, `ClaimItem`, `SourceDrawer` and `ProviderBadge`.
4. **85-90:** Add `FinancialTrend`, error states and `Disclaimer`.

Get real data on screen first, using simple cards, and refine the look afterwards.

**Passes when:** a ticker goes in, live progress shows, and a full briefing renders with source links. A bad ticker gets a clear message.

**Status:** passed on 2026-11-04, tested in a real browser with AAPL, a bad ticker typed into the input, and JPM on Groq. Each briefing made one request, with no console errors. The production build type-checks and its bundle contains no API keys. There's no sideways scrolling at phone width.

**Changed to fit the time:** components are written directly in Tailwind rather than shadcn/ui, so accessibility was done by hand: labels, focus rings, native `details` elements and icons beside color. The trend chart, tabs and source drawer are cut, and quotes expand inline instead. Recharts isn't installed. There are no frontend automated tests, so the rehearsal has to cover the UI.

**Start both servers from the app's preview, or in two terminals as above.** `.claude/launch.json` is in the folder above `Project/`.

**Checkpoint at minute 90: save a working copy.** The core demo now works, and everything later is optional.

### Phase 6: Follow-up agent (90-108 min)

**Package:** `langchain` (`create_agent`)

1. Build the three tools from the Phase 2 functions.
2. Create the agent with a limit on tool steps and the same no-recommendations rule.
3. Connect it to `POST /api/chat`.
4. Build `ChatPanel`, and show which tools were used.
5. If Gemini fails, rerun the question on Groq with the limits in section 4. Groq's docs say `openai/gpt-oss-120b` doesn't support parallel tool use, so turn it off and make tool calls one at a time.

**Passes when:** "How did revenue change, and what risks does management flag?" uses at least two tools and answers correctly in the chat panel.

**Status:** passed on 2026-11-04 in a real browser, on AAPL. The question used the financials and filing tools, and each year's figure was correct. A follow-up on net income used the conversation's context and matched the table. On Groq, a price and tariffs question used two tools. `check_agent.py` passed 3 of 3 live checks on one company only, with unit tests too.

**What the live run found:** Groq first attached real figures to the wrong years ($416.2B to fiscal 2024), and added a calculated figure, while the check still passed. The tools now list years oldest first with labeled rows and provide the changes, and `check_agent.py` fails on that error. Any dollar or percent figure not found in the tool results is now flagged beneath the answer.

**Limits to state openly:** chat answers aren't quote-checked like the summary, and the panel says so. The figure check can't catch a real figure attached to the wrong year, so that fix has only been shown on this one question. Qualitative statements aren't checked by code at all. First answers took about 24 s on Gemini and about 2 s on Groq.

### Final check results (2026-11-04)

These are the results before the Phase 7 prompt fix, and are kept for comparison. See Phase 7 for the final numbers.

| Provider | Tickers | Quotes verified | First-run total time |
|---|---|---|---|
| Gemini (full) | 10: AAPL, MSFT, NVDA, JPM, XOM, TSLA, WMT, PFE, GOOGL, ORCL | 115 of 134 (86%), ranging from 53% (WMT) to 100% | 16 to about 47 s, for the runs timed |
| Groq (reduced) | 3: AAPL, JPM, WMT | 28 of 34 (82%) | 2 to 18 s |

**How to read the flags:** the check is deliberately strict. WMT's 53% is mostly table values rounded by Gemini (`$706,413` million written as "$706.4 billion") or percentages it calculated, so many flagged claims may be fair but need checking. Measured here: whether each quote exists and contains the amounts. Not measured: whether each claim is a fair reading of its quote.

**What the final check found and fixed:**

- Two more false rejections: a non-breaking hyphen in "10-K", and the day in a date added for context.
- On ORCL, Gemini returned 503 twice and Groq then returned an intermittent `json_validate_failed`, so there was no summary. Groq now gets one retry for that error. The retry has unit tests, but hasn't yet fired in a live run.
- On WMT, a real Gemini overload moved to a labeled Groq briefing automatically, in 18 s.

**Saved for the demo (load in about 1 to 2 s):** all 10 tickers above on Gemini, and AAPL, JPM and WMT on Groq. `KO` is deliberately unsaved, for rehearsing a real first run. Chat answers aren't saved.

**Before the demo:** restart isn't needed unless code changes. If a briefing shows no summary, both LLMs were busy, and resubmitting tries again.

### Phase 7: Hardening and evals (108-120 min)

**Package:** `pytest`, plus `evals.py`

1. Run `evals.py` across the tickers below.
2. Fix the worst failure only.
3. Save demo data.
4. Rehearse the whole demo, including the forced failover.

**Passes when:** results are recorded for the slide and the rehearsal runs from start to finish.

**Status:** results are recorded and every rehearsal step ran, but **one item is still open**: the forced Groq failover on a new ticker failed on a rate limit. The fix is unit-tested, and its live test was stopped to save free quota.

**Final results** (`backend/eval_results.md`, mostly one run per company and LLM, so a small sample):

| Provider | Companies | Quotes verified | Range by company | Required sections found | Median tokens (in + out) | Median LLM time |
|---|---|---|---|---|---|---|
| Gemini (full) | 10 | 150 of 158 (95%) | 85% to 100% | 30 of 30 | 30,467 + 1,667 | 18.6 s |
| Groq (reduced) | 3 | 31 of 34 (91%) | 85% to 100% | 9 of 9 | 4,914 + 1,317 | 3.6 s |

The prompt was tuned using these companies, so these rates may be flattering. Disney, which wasn't used for tuning, verified 19 of 19, but that's one company.

**Worst failure fixed:** Gemini was rounding table values and calculating percentages, which took WMT to 8 of 15. The check wasn't loosened. A prompt change asks for figures exactly as shown, and took WMT to 16 of 16, and the overall rate from 86% to 95%.

**Rehearsal in the browser:**

- AAPL loaded from saved data in about 3 s, and its quote opens inline.
- The linked SEC filing opened, and the quote checked was in it.
- A follow-up answered correctly in about 30 s, with correct figures for each year.
- A first-run DIS briefing took about 40 s or less.
- A follow-up on Groq was accurate, and didn't invent a change figure.
- The forced Groq briefing on DIS hit Groq's per-minute limit, and the app labeled and used a saved analysis instead. See the open item above.

**To confirm the open item (uses about 6,000 Groq tokens):** tick "Use backup LLM", wait at least a minute after other Groq use, and run a ticker with no Groq briefing saved, such as `KO`.

### Live quote refresh (added after Phase 7)

While a briefing is on screen, the page refreshes the quote every 30 seconds through `GET /api/quotes/{ticker}`, using no LLM quota. It stops while the tab is hidden. If an update fails or only a saved quote exists, the last price stays and the page says updates are paused. Tested in a real browser on AAPL, including stopping and restarting the backend. The financials, summary and filings don't refresh, because they come from filings that only change on a new report. The saved-quote branch of the pause logic was checked by reading the code only.

### Phase 8 status

**Status:** done on 2026-11-04. The slide is `Financial Data Summarizer_deck.pptx`, and its speaker notes hold a 2-minute talk track. The file passed validation. It was only previewed with macOS Quick Look, which substitutes fonts, so open it once in PowerPoint before presenting.

### Evals

**Suggested eval tickers:** AAPL, JPM (bank, different tags and layout), MSFT, XOM (reorganized, with its 10-K under the old registrant), and one that should fail cleanly such as ASML (20-F) or an invalid ticker.

**Metrics to report:** share of quotes verified, sections extracted successfully, and time per briefing. Use whatever the run actually shows.

## 6. Cut lines if time runs short

**Time check at minute 55:** if the briefing engine isn't working yet, finish it first and take the time from the UI list below. A plain page with real data beats a polished page with none.

Cut in this order:

1. UI extras: trend chart (keep the table), then tabs (use one scrolling page), then the source drawer (show quotes inline).
2. Streaming: replace it with a normal request and a loading spinner if it isn't working within 5 minutes.
3. Eval script: run 3 tickers by hand instead.
4. "Questions a client may ask" section.
5. Latest 10-Q: use the 10-K only and say so.
6. Follow-up agent. **Only cut this as a last resort, as this role is about agentic engineering.** If it goes, walk through its design instead.

**Never cut:** React page showing the latest available quote when it passes the freshness policy, filing summary, source links and quote verification.

**Add only if ahead of schedule:**

- Comparison of risk factors against the prior year's 10-K, showing what changed. This is the most useful extra for advisors.
- Tracing with Langfuse or Arize Phoenix.
- Recent 8-K events.

## 7. Slide (one page)

- **Title:** the outcome, for example "From ticker to trusted briefing". Add "in under a minute" only if the Phase 7 results support it.
- **Problem:** advisors spend time gathering information before they can advise. Do not quote a time saving unless it is measured or labeled as an assumption.
- **Solution:** a small version of the flow diagram.
- **Why trust it:** official sources, numbers shown directly, verified quotes, no recommendations.
- **Results:** actual numbers from the eval run.
- **Status:** what was implemented, and what isn't done or isn't proven.
- **Path to production:** licensed market data, single sign-on, audit logs, compliance review, CRM integration, and a pilot with success measures.

## 8. Interview

### Demo (about 8 minutes of the 20)

1. Show the slide and the problem (2 min).
2. Run AAPL and walk through the briefing (2 min).
3. Open a source and show a verified quote against the filing (1 min).
4. Ask a follow-up that uses tools (1 min).
5. **Let the panel choose a ticker** (2 min).

If time allows, turn on `FORCE_LLM_FAILOVER` and show the labeled Groq briefing. Keep saved data ready if a live source fails, and say so openly if you use it.

### Points to narrate during the build

- Why a fixed pipeline for the briefing and an agent for follow-ups.
- Why the LLM never produces the displayed financial figures.
- What you are cutting and why, as each tradeoff comes up.
- Anything that breaks, what you learned, and how you adjusted.

### Questions to prepare for

| Question | Answer to prepare |
|---|---|
| How do we know it is accurate? | Figures come straight from sources, and quotes are checked. Be open that a real quote can still be summarized badly, so advisors review it and production needs human-reviewed evals |
| Is this investment advice? | No. It summarizes facts and makes no recommendations; compliance review is needed before rollout |
| Is the quote data reliable? | Not for production. Call it "latest available," show the exact market timestamp, and never infer real-time delivery from recency. Yahoo is unofficial, so a licensed vendor would replace it |
| What does it cost? | Measure tokens per briefing during the build and use the real number |
| Why React and FastAPI rather than a quick Python UI? | It keeps API keys on the server, shows how this would look to real users, and lets the backend serve other clients such as a CRM later. It cost development time, which is why tests focus on the backend |
| Why Gemini and Groq? | Two independent providers keep the demo running if one fails, and `llm.py` makes them easy to swap. In production, a gateway such as Portkey could centralize keys, routing and logging |
| What if the two providers disagree? | They can. The UI shows which one answered, quote verification runs on both, and Groq output is labeled as reduced |
| How does it scale? | Cache by filing, as filings do not change; refresh quotes separately |
| What about client data? | The prototype sends only public data to the LLMs. Production needs a review of each provider's data terms, paid or enterprise plans, access controls and audit logs |
| What would you do with more time? | Risk factor changes, 8-Ks, earnings calls, tracing, and a human-reviewed eval set |

## 9. Risks

| Risk | Likelihood | Response |
|---|---|---|
| Tool calling or structured output fails on a model (not yet tested with keys) | Medium | Test both in Phase 1. Change the model in `.env`, or use a simple router that picks a tool using structured output |
| Gemini is overloaded during the demo | **High, seen repeatedly on 2026-11-04** | Automatic Groq fallback, plus saved briefings for the demo tickers. Retest models on the day. In 8 test calls each: `gemini-3.5-flash-lite` had 8 successes but averaged 15 s, `gemini-3.6-flash` had 6 successes (two 429s) at 2 s, and `gemini-3.8-flash` had none (503s and a 504) |
| Groq limits are too low for the fallback | Medium | Reduced briefing; check your account's limits beforehand; use cached briefings if needed |
| Groq fallback gives weaker output | Medium | Label it as reduced, and rely on quote verification to flag unsupported claims |
| Yahoo rate-limits during the demo | Medium | Backup endpoint, then apply the freshness policy to the last-saved quote. Suppress a stale intraday price rather than presenting it as current |
| Section extraction fails on a company not yet tested | Medium | Longest-match rule, then name search, then a visible warning; `check_data.py` covers 7 companies so far |
| Slow LLM calls during the demo | Medium | Show progress, and save analyses so repeat runs are instant |
| Advice filter misses a recommendation, as it only matches set phrases | Low | The prompt forbids advice too; a compliance review is needed before production |
| React work overruns and takes time from the agent | Medium | Use the minute 55 time check and UI cuts in section 6; get real data on screen before styling |
| Frontend tool setup fails or versions clash | Medium | Test the scaffold beforehand (section 10), and use what the Vite template installs if a pinned version clashes |
| Streaming breaks through the Vite proxy | Low | Replace it with a normal request and a spinner |
| Agent loops or gives a poor answer | Low | Limit tool steps, and rehearse the demo questions |

## 10. Before the interview

**Check before using pre-built code in the assessed session.** The instructions describe designing and building within the session, and the recording is part of the assessment. Treat any earlier build as practice, unless the recruiter confirms that you can bring it.

The backend environment is ready, using Python 3.12 and the versions in section 4:

```bash
conda activate proto
```

To recreate it elsewhere:

```bash
conda create -n proto python=3.12 -y
```

```bash
pip install -r backend/requirements.txt
```

Node 26.13.0 and npm 11.20.0 are already installed. Test the frontend scaffold once in a throwaway folder outside `Project/`, then delete it. The Tailwind and shadcn/ui steps change between versions, so follow their current Vite guides as you go:

```bash
npm create vite@latest scaffold-test -- --template react-ts
```

Checklist:

- [ ] Confirm with the recruiter whether the 2.5 hours includes the interview
- [ ] Confirm with the recruiter that your own Gemini and Groq keys are acceptable
- [x] Python environment installed, and `python -c "import fastapi, langchain"` runs cleanly
- [ ] Throwaway Vite app runs with Tailwind and one shadcn/ui component, then is deleted
- [x] Create a Gemini API key in Google AI Studio (still note your model limits there)
- [x] Create a Groq API key (still note your limits for `openai/gpt-oss-120b` in your account settings)
- [ ] Send one test message with each key, then check that both model names still work on the day
- [x] Prepare `SEC_USER_AGENT` with your real name and email
- [ ] Check screen sharing and that Claude Code works on the interview network

Both keys, structured output and tool calling passed live checks on 2026-11-04. Limits come from the provider docs, so check them for your own accounts, and recheck model availability on the day.

## 11. Definition of done

- [ ] Any valid US-listed 10-K filer returns a briefing, tested live on a ticker the panel chooses
- [ ] Quote shows its source and as-of time, never claims "real-time" without a provider guarantee, and is suppressed when it fails the freshness policy
- [ ] Every summary claim links to a filing and shows its verification status
- [ ] Follow-up question answered in the chat panel using at least one tool
- [ ] React UI shows live progress, and has clear loading, error and saved-data states
- [ ] No API key reaches the browser (check the network tab)
- [ ] Forced failover produces a labeled Groq briefing and a follow-up answer
- [ ] Invalid tickers and companies without a 10-K get a clear message
- [ ] No API keys visible in code or on screen
- [ ] One slide finished, using measured results
- [ ] Can explain each major tradeoff and what comes next
