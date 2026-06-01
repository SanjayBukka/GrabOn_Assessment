# GrabOn Merchant Deal Audit Agent

## What I Built

I built an autonomous audit agent for GrabOn merchant pages. It scrapes live coupon pages, extracts deals, compares them with a mock internal DB, classifies differences, and writes a report with cost, latency, tool, and recovery details.

I chose this assignment because it tests the real hard parts of agent systems: unreliable websites, imperfect LLM output, fallback routing, budget limits, and explainable failure recovery.

## Architecture

```text
+------------------+
| main.py          |
| load merchants   |
+--------+---------+
         |
         v
+-----------------------------+
| AgentLoop                   |
| for each merchant           |
| Amazon -> Myntra -> Zomato  |
+-------------+---------------+
              |
              v
      +----------------+
      | PLAN           |
      | AgentPlanner   |
      +-------+--------+
              |
              v
      +----------------+
      | ACT            |
      | ToolRegistry   |
      +-------+--------+
              |
              v
      +----------------+
      | OBSERVE        |
      | success/error  |
      +-------+--------+
              |
              v
      +-------------------------------+
      | DECIDE                        |
      | continue / retry / switch     |
      | replan / fail merchant        |
      +---+-----------------------+---+
          |                       |
          | continue              | retry / switch / replan
          v                       |
   next tool or done <------------+

+-----------------------------+       +-----------------------------+
| Tool Layer                  |       | LLM Layer                   |
| scrape_html                 |       | Groq: planning/classify     |
| google_cache                |       | Gemini Flash: extraction    |
| scrape_js                   |       | OpenRouter: fallback        |
| static_template             |       | shadow_test comparisons     |
| extract_deals               |       | per-task cost tracking      |
| db_lookup                   |       +-----------------------------+
| classify_deals              |
| verify_coupon               |
+--------------+--------------+
               |
               v
+-----------------------------+
| State + Guardrails          |
| AgentState                  |
| BudgetEnforcer              |
| tokens/time/tools/failures  |
+--------------+--------------+
               |
               v
+-----------------------------+
| Outputs                     |
| Rich terminal dashboard     |
| LangSmith traces            |
| reports/audit_<time>.json   |
+-----------------------------+
```

## Module Design and Tradeoffs

- `agent/loop.py`: explicit PLAN/ACT/OBSERVE/DECIDE loop. More verbose than a hidden framework flow, but easier to debug and explain.
- `agent/planner.py`: LLM-driven plan and replan logic with safe defaults when providers fail.
- `tools/registry.py`: one wrapper for timeout, stats, validation, and error handling. Tradeoff: each tool must return consistent structured output.
- `tools/deal_extractor.py`: BeautifulSoup pre-filtering plus LLM extraction and hidden-code detection. This keeps token usage low while still catching GrabOn coupon attributes.
- `tools/deal_classifier.py`: deterministic comparison between DB and live deals. I kept classification non-LLM so audit labels stay stable.
- `llm/router.py`: task-based routing, fallback providers, shadow testing, and per-task cost tracking.
- `agent/budget.py`: hard limits stop runaway runs. Tradeoff: a partial report may be produced instead of forcing completion.
- `evals/`: 15 focused scenarios covering happy path, recovery, budgets, edge cases, and multi-LLM behavior.

## How to Run

Prerequisites: Python 3.10+, Playwright Chromium, and API keys for Groq, Google Gemini, and OpenRouter.

```powershell
python -m venv venv
.\venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install chromium
copy .env.example .env
```

Fill these environment variables in `.env`:

```env
GROQ_API_KEY=your_groq_key_here
GOOGLE_API_KEY=your_gemini_key_here
OPENROUTER_API_KEY=your_openrouter_key_here

LANGCHAIN_TRACING_V2=true
LANGCHAIN_ENDPOINT=https://api.smith.langchain.com
LANGCHAIN_API_KEY=your_langsmith_key_here
LANGCHAIN_PROJECT=grabon-audit-agent

MAX_TOKENS_PER_RUN=150000
MAX_WALL_CLOCK_SECONDS=900
MAX_TOOL_CALLS=200
MAX_CONSECUTIVE_FAILURES=5

SCRAPE_DELAY_SECONDS=2
USE_PLAYWRIGHT=true

GROQ_INPUT_COST=0.05
GROQ_OUTPUT_COST=0.08
GEMINI_INPUT_COST=0.075
GEMINI_OUTPUT_COST=0.30
OPENROUTER_INPUT_COST=0.10
OPENROUTER_OUTPUT_COST=0.20
```

Pinned dependencies are in `requirements.txt`: LangGraph, LangChain, Groq, Google GenAI, OpenAI/OpenRouter client, LangSmith, httpx, Playwright, BeautifulSoup, lxml, Pydantic, Rich, python-dotenv, pytest, tenacity, aiofiles, python-dateutil, and nest-asyncio.

Useful commands:

```powershell
python main.py --eval
python main.py --merchants 3
python main.py --merchant amazon
python main.py
```

Outputs:

- Reports: `reports/audit_<timestamp>.json`
- Traces: LangSmith project from `LANGCHAIN_PROJECT`
- Live progress: terminal dashboard

## Eval Results

Latest local eval suite:

- Scenarios: 15
- Pass rate: 15/15, 100%
- Accuracy: 100% against deterministic expected outcomes
- Eval cost: $0, because scenarios use mocked responses
- Eval latency: each mocked scenario reports 0ms; full command is about 5 seconds locally including imports and setup

Latest live smoke target:

- Command: `python main.py --merchants 3`
- Expected behavior: 3/3 merchants complete, positive runtime, no terminal crash, deals extracted from live pages when available
- Live cost and latency vary by provider limits and website response time

## What Broke First

The hardest bug was that the report looked successful while hiding empty or wrong merchant results. The loop completed tool calls, but the final `MerchantResult` was not always appended and the report summary was not reliably aggregated from `state.merchant_results`.

I fixed it by making merchant completion write one final structured result, generating the report from stored state, and tightening recovery paths so retries, replans, and fallbacks still produce inspectable output.

Technical scenarios I handled:

- Scenario 1: Amazon looked successful but produced `live_deals_count = 0`. The scraper returned HTML, so the agent marked the scrape as successful, but the coupon codes were hidden in `data-clipboard-text` instead of visible page text. I adjusted `deal_extractor.py` to scan coupon-like attributes first, prepend discovered codes to the LLM prompt, and only then send a trimmed HTML slice.
- Scenario 2: Myntra returned a 403 during raw scraping. The OBSERVE phase classified it as `RATE_LIMIT`, and DECIDE switched the next action from `scrape_html` to `google_cache`. I added structured error types so the agent could choose a recovery path instead of treating all scraper failures the same.
- Scenario 3: Zomato loaded an almost empty static page because the coupon cards were rendered later by JavaScript. The agent saw successful HTTP status but empty HTML, so I added an empty-content check that routes to `scrape_js` using Playwright. This separated "page fetched" from "page has usable evidence."
- Scenario 4: The extractor sometimes returned invalid JSON or `min_order: null`. That crashed record validation. I tightened the prompt, added retry behavior for malformed JSON, and normalized nullable fields like `min_order` to `0` before creating `DealRecord`.
- Scenario 5: A planning model became unavailable during testing. I updated model names and added provider fallback order in `llm/router.py`, so planning can move from Groq to Gemini/OpenRouter/Groq-small while still recording task-level cost and provider used.

## What I Would Change With 2 More Weeks

- Replace `data/mock_db.json` with a real internal deals API and schema validation.
- Add persistent caching for scraped HTML and LLM extraction results to reduce cost and latency.
- Build merchant-specific extraction rules for pages that lazy-load codes.
- Improve matching with normalized coupon aliases, fuzzy discount matching, and confidence scores.
- Add a small dashboard for trend history, failed merchants, and manual review queues.
