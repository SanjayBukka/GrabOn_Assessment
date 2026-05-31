# 🤖 GrabOn Merchant Deal Audit Agent — Complete Build Instructions

> **For:** Claude Haiku 4.5 in VS Code  
> **Developer:** Sanjay (Windows 11, i7-13620H, 16GB RAM)  
> **Goal:** Build a production-grade autonomous agent that audits GrabOn's deal pages and produces a structured audit report — with full Plan/Act/Observe/Decide loop, failure recovery, budget enforcement, multi-LLM routing, LangSmith tracing, and an eval suite.

---

## ⚠️ CRITICAL CODING INSTRUCTIONS (Read Before Writing Any Code)

1. **No hallucinated imports.** Every import must be a real, installable package. If unsure, check PyPI first.
2. **No dead functions.** Every function defined must be called somewhere.
3. **No placeholder TODOs left in final code.** Implement everything or remove it.
4. **Every tool must have a Pydantic schema.** No raw dicts passed between tools.
5. **Every file must have a module docstring** explaining what it does.
6. **LangSmith tracing must wrap the entire agent loop** — not just individual LLM calls.
7. **Rich terminal must show live updates** — not print statements dumped at the end.
8. **All API keys must come from `.env`** — never hardcoded.
9. **After writing each file, verify imports resolve** before moving to the next file.
10. **The agent loop class must be named exactly `AgentLoop`** — the evaluator will look for it.

---

## 📁 Exact Project Structure to Create

```
GRABON_ASSIGNMENT/
├── .env.example
├── .gitignore
├── README.md
├── requirements.txt
├── main.py                        # Entry point
├── agent/
│   ├── __init__.py
│   ├── loop.py                    # AgentLoop class — PLAN/ACT/OBSERVE/DECIDE
│   ├── state.py                   # AgentState Pydantic model
│   ├── budget.py                  # BudgetEnforcer class
│   └── planner.py                 # LLM-based planner
├── tools/
│   ├── __init__.py
│   ├── registry.py                # ToolRegistry — dynamic discovery
│   ├── scraper_html.py            # Tool 1: Raw HTTP scraper
│   ├── scraper_js.py              # Tool 2: Playwright JS scraper
│   ├── google_cache.py            # Tool 3: Google Cache fallback
│   ├── deal_extractor.py          # Tool 4: LLM deal extraction
│   ├── db_lookup.py               # Tool 5: Mock DB query
│   ├── deal_classifier.py         # Tool 6: Fresh/Stale/Missing/Updated
│   └── unreliable_verifier.py     # Tool 7: Fails 30% of time (intentional)
├── data/
│   ├── merchants.json             # 20 merchants with URLs
│   ├── mock_db.json               # GrabOn's "internal" deal database
│   └── scraped/                   # Auto-created, stores raw scraped HTML
├── llm/
│   ├── __init__.py
│   ├── router.py                  # Multi-LLM router (Groq/Gemini/OpenRouter/Nvidia)
│   └── cost_tracker.py            # Per-call cost tracking
├── observability/
│   ├── __init__.py
│   ├── terminal_ui.py             # Rich terminal dashboard
│   └── langsmith_tracer.py        # LangSmith integration
├── evals/
│   ├── __init__.py
│   ├── scenarios.py               # 30+ test scenarios defined here
│   ├── runner.py                  # Eval harness
│   └── fixtures/                  # Mock responses for eval
│       ├── happy_path.json
│       ├── failure_cases.json
│       └── budget_exceeded.json
└── reports/                       # Auto-created, final audit reports saved here
```

---

## 🗄️ Step 1 — Create the Data Files First

### `data/merchants.json`
```json
[
  {"id": "amazon", "name": "Amazon", "url": "https://www.grabon.in/amazon-coupons/", "category": "ecommerce"},
  {"id": "myntra", "name": "Myntra", "url": "https://www.grabon.in/myntra-coupons/", "category": "fashion"},
  {"id": "zomato", "name": "Zomato", "url": "https://www.grabon.in/zomato-coupons/", "category": "food"},
  {"id": "swiggy", "name": "Swiggy", "url": "https://www.grabon.in/swiggy-coupons/", "category": "food"},
  {"id": "flipkart", "name": "Flipkart", "url": "https://www.grabon.in/flipkart-coupons/", "category": "ecommerce"},
  {"id": "nykaa", "name": "Nykaa", "url": "https://www.grabon.in/nykaa-coupons/", "category": "beauty"},
  {"id": "ajio", "name": "Ajio", "url": "https://www.grabon.in/ajio-coupons/", "category": "fashion"},
  {"id": "makemytrip", "name": "MakeMyTrip", "url": "https://www.grabon.in/makemytrip-coupons/", "category": "travel"},
  {"id": "puma", "name": "Puma", "url": "https://www.grabon.in/puma-coupons/", "category": "sports"},
  {"id": "boat", "name": "boAt", "url": "https://www.grabon.in/boat-coupons/", "category": "electronics"},
  {"id": "cred", "name": "CRED", "url": "https://www.grabon.in/cred-coupons/", "category": "fintech"},
  {"id": "meesho", "name": "Meesho", "url": "https://www.grabon.in/meesho-coupons/", "category": "ecommerce"},
  {"id": "blinkit", "name": "Blinkit", "url": "https://www.grabon.in/blinkit-coupons/", "category": "grocery"},
  {"id": "tatacliq", "name": "Tata CLiQ", "url": "https://www.grabon.in/tatacliq-coupons/", "category": "ecommerce"},
  {"id": "shopsy", "name": "Shopsy", "url": "https://www.grabon.in/shopsy-coupons/", "category": "ecommerce"},
  {"id": "zepto", "name": "Zepto", "url": "https://www.grabon.in/zepto-coupons/", "category": "grocery"},
  {"id": "bigbasket", "name": "BigBasket", "url": "https://www.grabon.in/bigbasket-coupons/", "category": "grocery"},
  {"id": "dominos", "name": "Domino's", "url": "https://www.grabon.in/dominos-coupons/", "category": "food"},
  {"id": "mcdonald", "name": "McDonald's", "url": "https://www.grabon.in/mcdonalds-coupons/", "category": "food"},
  {"id": "netmeds", "name": "Netmeds", "url": "https://www.grabon.in/netmeds-coupons/", "category": "pharma"}
]
```

### `data/mock_db.json`
> This is GrabOn's "internal database" — intentionally has some wrong/stale/missing entries so the agent finds mismatches.

```json
{
  "version": "2024-01-15",
  "deals": [
    {"merchant_id": "amazon", "code": "AMZNEW10", "discount": "10%", "description": "10% off on electronics", "expiry": "2025-12-31", "min_order": 500, "status": "active"},
    {"merchant_id": "amazon", "code": "PRIMESAVE", "discount": "15%", "description": "15% off for Prime members", "expiry": "2025-06-30", "min_order": 0, "status": "active"},
    {"merchant_id": "myntra", "code": "MYNTRA30", "discount": "30%", "description": "30% off on fashion", "expiry": "2024-05-15", "min_order": 799, "status": "active"},
    {"merchant_id": "myntra", "code": "STYLE20", "discount": "20%", "description": "20% off sitewide", "expiry": "2025-12-31", "min_order": 999, "status": "active"},
    {"merchant_id": "zomato", "code": "ZOM100", "discount": "₹100 off", "description": "Flat Rs 100 off on orders above 299", "expiry": "2025-12-31", "min_order": 299, "status": "active"},
    {"merchant_id": "zomato", "code": "ZOMGOLD", "discount": "40%", "description": "40% off for Gold members", "expiry": "2025-03-31", "min_order": 0, "status": "active"},
    {"merchant_id": "swiggy", "code": "SWIGGY40", "discount": "40%", "description": "40% off up to Rs 80", "expiry": "2025-12-31", "min_order": 199, "status": "active"},
    {"merchant_id": "flipkart", "code": "FLIPNEW", "discount": "25%", "description": "25% off for new users", "expiry": "2025-12-31", "min_order": 0, "status": "active"},
    {"merchant_id": "nykaa", "code": "NYKAA20", "discount": "20%", "description": "20% off on beauty", "expiry": "2025-09-30", "min_order": 699, "status": "active"},
    {"merchant_id": "ajio", "code": "AJIO30", "discount": "30%", "description": "30% off on brands", "expiry": "2025-12-31", "min_order": 1299, "status": "active"},
    {"merchant_id": "makemytrip", "code": "MMTFLIGHT", "discount": "₹500 off", "description": "Rs 500 off on domestic flights", "expiry": "2025-12-31", "min_order": 3000, "status": "active"},
    {"merchant_id": "puma", "code": "PUMA25", "discount": "25%", "description": "25% off on shoes", "expiry": "2025-06-30", "min_order": 2999, "status": "active"},
    {"merchant_id": "boat", "code": "BOATSAVE", "discount": "15%", "description": "15% off on earbuds", "expiry": "2025-12-31", "min_order": 999, "status": "active"},
    {"merchant_id": "cred", "code": "CREDCASH", "discount": "₹200 off", "description": "Rs 200 cashback on bill payments", "expiry": "2025-12-31", "min_order": 1000, "status": "active"},
    {"merchant_id": "meesho", "code": "MEESHO99", "discount": "₹99 off", "description": "Rs 99 off on first order", "expiry": "2024-12-31", "min_order": 0, "status": "active"},
    {"merchant_id": "blinkit", "code": "BLINK50", "discount": "₹50 off", "description": "Rs 50 off on groceries", "expiry": "2025-12-31", "min_order": 299, "status": "active"},
    {"merchant_id": "tatacliq", "code": "TATA15", "discount": "15%", "description": "15% off on Tata products", "expiry": "2025-12-31", "min_order": 1499, "status": "active"},
    {"merchant_id": "dominos", "code": "DOM50", "discount": "₹50 off", "description": "Rs 50 off on pizza orders", "expiry": "2025-12-31", "min_order": 299, "status": "active"},
    {"merchant_id": "netmeds", "code": "MED20", "discount": "20%", "description": "20% off on medicines", "expiry": "2025-12-31", "min_order": 599, "status": "active"}
  ]
}
```
> **Note:** `zepto`, `shopsy`, `mcdonald` are intentionally missing from DB — agent will classify them as `Missing`. `myntra/MYNTRA30` has a past expiry date — agent should catch it as `Stale`.

---

## 🔧 Step 2 — `requirements.txt`

```txt
# Core agent framework
langgraph==0.2.28
langchain==0.3.7
langchain-core==0.3.15
langchain-groq==0.2.1
langchain-google-genai==2.0.4
langsmith==0.1.140

# Web scraping
httpx==0.27.2
playwright==1.48.0
beautifulsoup4==4.12.3
lxml==5.3.0

# Data validation
pydantic==2.9.2
pydantic-settings==2.6.1

# Terminal UI
rich==13.9.4

# Environment
python-dotenv==1.0.1

# Testing
pytest==8.3.3
pytest-asyncio==0.24.0
pytest-cov==6.0.0

# Utilities
tenacity==9.0.0
aiofiles==24.1.0
python-dateutil==2.9.0
```

---

## 🔑 Step 3 — `.env.example`

```env
# === LLM PROVIDERS ===
GROQ_API_KEY=your_groq_key_here
GOOGLE_API_KEY=your_gemini_key_here
OPENROUTER_API_KEY=your_openrouter_key_here
NVIDIA_API_KEY=your_nvidia_key_here

# === LANGSMITH (Tracing) ===
LANGCHAIN_TRACING_V2=true
LANGCHAIN_ENDPOINT=https://api.smith.langchain.com
LANGCHAIN_API_KEY=your_langsmith_key_here
LANGCHAIN_PROJECT=grabon-audit-agent

# === AGENT BUDGET LIMITS ===
MAX_TOKENS_PER_RUN=150000
MAX_WALL_CLOCK_SECONDS=900
MAX_TOOL_CALLS=200
MAX_CONSECUTIVE_FAILURES=5

# === SCRAPING ===
SCRAPE_DELAY_SECONDS=2
USE_PLAYWRIGHT=true

# === COST TRACKING (USD per 1M tokens) ===
GROQ_INPUT_COST=0.05
GROQ_OUTPUT_COST=0.08
GEMINI_INPUT_COST=0.075
GEMINI_OUTPUT_COST=0.30
OPENROUTER_INPUT_COST=0.10
OPENROUTER_OUTPUT_COST=0.20
NVIDIA_INPUT_COST=0.40
NVIDIA_OUTPUT_COST=0.40
```

---

## 🧠 Step 4 — Core Files to Build (In This Order)

### ORDER OF IMPLEMENTATION
Build in this exact sequence. Each file depends on the previous:

```
1. agent/state.py          ← Pydantic models for all state
2. llm/cost_tracker.py     ← Cost tracking before any LLM calls
3. llm/router.py           ← Multi-LLM router
4. tools/registry.py       ← Tool registry before any tools
5. tools/scraper_html.py   ← Tool 1
6. tools/google_cache.py   ← Tool 2 (fallback for Tool 1)
7. tools/scraper_js.py     ← Tool 3 (fallback for Cloudflare)
8. tools/deal_extractor.py ← Tool 4 (LLM-powered)
9. tools/db_lookup.py      ← Tool 5
10. tools/deal_classifier.py ← Tool 6
11. tools/unreliable_verifier.py ← Tool 7 (intentional failures)
12. agent/budget.py        ← Budget enforcement
13. agent/planner.py       ← LLM planner
14. observability/terminal_ui.py ← Rich UI
15. observability/langsmith_tracer.py ← Tracing
16. agent/loop.py          ← Main AgentLoop class (PLAN/ACT/OBSERVE/DECIDE)
17. main.py                ← Entry point
18. evals/scenarios.py     ← 30 test scenarios
19. evals/runner.py        ← Eval harness
```

---

## 📋 Step 5 — Detailed Spec for Each File

---

### `agent/state.py`
```
Define these Pydantic models:

- DealStatus: Enum → FRESH, STALE, MISSING, UPDATED, UNKNOWN, ERROR
- DealRecord: code, discount, description, expiry, min_order, source (DB or LIVE)
- MerchantResult: merchant_id, name, url, db_deals (list), live_deals (list), 
                  classified_deals (list), status, error_message, 
                  tool_calls_used (int), time_taken (float)
- AgentIteration: step_number, phase (PLAN/ACT/OBSERVE/DECIDE), action, 
                  tool_called, observation, decision, tokens_consumed, 
                  wall_clock_time, llm_provider, cost_usd
- AgentState: session_id, start_time, merchants_total, merchants_completed,
              merchants_failed, current_merchant, iterations (list of AgentIteration),
              total_tokens, total_cost_usd, total_tool_calls, consecutive_failures,
              budget_exceeded (bool), final_report (dict or None)
```

---

### `llm/router.py`
```
Class: LLMRouter

Rules for which model to use for which task:
- PLANNING task → Groq (llama-3.1-70b-versatile) — fast, good at reasoning
- DEAL_EXTRACTION task → Gemini Flash (gemini-1.5-flash) — good at HTML parsing
- CLASSIFICATION task → Groq (llama-3.1-8b-instant) — cheap, fast, simple task  
- FALLBACK_EXTRACTION task → OpenRouter (meta-llama/llama-3.2-3b-instruct:free) — free tier
- IMPOSSIBLE_DETECTION task → Nvidia (meta/llama-3.1-70b-instruct) — high accuracy

Methods:
- get_llm(task_type: str) → returns configured LLM client
- call_with_tracking(task_type, prompt, max_tokens) → returns (response, tokens_used, cost_usd, provider_name)
- get_cost_summary() → returns dict with per-provider breakdown

Important: Each call must be wrapped in try/except. If primary provider fails, 
fall back to next in chain. Log which provider was actually used.
```

---

### `tools/registry.py`
```
Class: ToolRegistry

- Tools are registered via a decorator @registry.register(name, description, cost_annotation)
- NOT hardcoded — tools are discovered by scanning the tools/ directory
- Each tool in registry has: name, function, description, schema (Pydantic), 
  timeout_seconds, cost_annotation, call_count, failure_count

Methods:
- register(name, description, timeout, cost) → decorator
- get_tool(name) → returns tool function
- list_tools() → returns all registered tools with metadata
- execute(name, **kwargs) → runs tool with timeout enforcement, 
                            returns ToolResult(success, data, error, latency_ms)
- get_stats() → returns per-tool call counts and failure rates

ToolResult model:
- success: bool
- data: dict | None
- error: str | None  
- error_type: Literal["TRANSIENT", "PERMANENT", "RATE_LIMIT", "NOT_FOUND", "TIMEOUT"] | None
- latency_ms: float
- tool_name: str
```

---

### `tools/scraper_html.py`
```
Tool Name: scrape_html
Description: Scrapes raw HTML from a GrabOn deal page using httpx

Input Schema (Pydantic):
- url: str
- timeout_seconds: int = 10
- delay_before: float = 2.0  ← always wait before scraping

Logic:
1. Wait delay_before seconds
2. Make GET request with rotating User-Agent headers
3. If status 200 → return HTML content + page title
4. If status 403/429 → return error_type=RATE_LIMIT
5. If status 404 → return error_type=NOT_FOUND
6. If timeout → return error_type=TIMEOUT
7. Store raw HTML to data/scraped/{merchant_id}_{timestamp}.html

User-Agent list to rotate:
- Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36
- Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36
- Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36

Output Schema:
- html: str | None
- page_title: str | None  
- status_code: int
- saved_path: str | None
- error_type: str | None
```

---

### `tools/google_cache.py`
```
Tool Name: google_cache
Description: Fetches cached version of page from Google Cache — fallback when direct scraping is blocked

Input Schema:
- original_url: str
- timeout_seconds: int = 15

Logic:
1. Construct Google Cache URL: 
   f"https://webcache.googleusercontent.com/search?q=cache:{original_url}"
2. Make GET with httpx
3. If success → strip Google Cache header, return clean HTML
4. If fails → try Bing Cache: f"https://cc.bingj.com/cache.aspx?q={original_url}"
5. If both fail → return error_type=PERMANENT

Output Schema: same as scraper_html
```

---

### `tools/scraper_js.py`
```
Tool Name: scrape_js
Description: Uses Playwright to scrape JS-rendered content — fallback for dynamic pages

Input Schema:
- url: str
- wait_for_selector: str = ".coupon-code"  ← GrabOn's coupon element class
- timeout_seconds: int = 30

Logic:
1. Launch Playwright chromium (headless=True)
2. Navigate to URL
3. Wait for wait_for_selector OR timeout
4. Extract page content after JS renders
5. Close browser
6. Return HTML

Note: Only use this tool if scrape_html returns empty or insufficient content.
It's slower (10-30s) so it's a secondary tool.

Output Schema: same as scraper_html
```

---

### `tools/deal_extractor.py`
```
Tool Name: extract_deals
Description: Uses LLM to extract structured deal data from raw HTML

Input Schema:
- html: str
- merchant_name: str
- merchant_id: str

LLM Task Type: DEAL_EXTRACTION → use Gemini Flash

Prompt to send to LLM:
"""
You are a deal extraction specialist. Extract all coupon codes and deals from this HTML.

Merchant: {merchant_name}
HTML Content: {html[:8000]}  ← truncate to 8000 chars

Return ONLY valid JSON in this exact format:
{
  "deals": [
    {
      "code": "COUPON123",
      "discount": "20% off",
      "description": "20% off on orders above Rs 499",
      "expiry": "2025-12-31",
      "min_order": 499,
      "conditions": "New users only"
    }
  ],
  "extraction_confidence": 0.95,
  "deals_found_count": 3
}

If no deals found, return: {"deals": [], "extraction_confidence": 0.0, "deals_found_count": 0}
Do NOT hallucinate coupon codes. Only extract what is explicitly visible in the HTML.
"""

Output Schema:
- deals: list[DealRecord]
- extraction_confidence: float
- deals_found_count: int
- llm_provider_used: str
- tokens_used: int
```

---

### `tools/db_lookup.py`
```
Tool Name: db_lookup
Description: Queries the mock GrabOn internal database for a merchant's deals

Input Schema:
- merchant_id: str

Logic:
1. Load data/mock_db.json
2. Filter by merchant_id
3. Return all deals for that merchant
4. If no deals found → return empty list (this is valid, not an error)

Output Schema:
- deals: list[DealRecord]
- merchant_found: bool
- deal_count: int
```

---

### `tools/deal_classifier.py`
```
Tool Name: classify_deals
Description: Compares live deals vs DB deals and classifies each

Input Schema:
- merchant_id: str
- db_deals: list[DealRecord]
- live_deals: list[DealRecord]

Classification Logic (implement in code, NOT via LLM):
- FRESH: code exists in DB AND on live page AND discount matches AND not expired
- STALE: code exists in DB AND on live page BUT discount changed OR expiry passed
- MISSING: code in DB but NOT found on live page at all
- UPDATED: code on live page with different discount than DB (DB needs updating)
- EXTRA: deal on live page but NOT in DB at all (new deal GrabOn needs to add)

Use LLM only for: edge cases where comparison is ambiguous (use CLASSIFICATION task → cheap model)

Output Schema:
- classified_deals: list with each deal having status field
- summary: {fresh: int, stale: int, missing: int, updated: int, extra: int}
- merchant_health_score: float  ← percentage of deals that are FRESH
```

---

### `tools/unreliable_verifier.py`
```
Tool Name: verify_coupon
Description: Verifies if a coupon code is genuinely active — INTENTIONALLY UNRELIABLE

Input Schema:
- merchant_id: str
- coupon_code: str

Logic:
1. import random
2. If random.random() < 0.30 → simulate failure:
   - Randomly pick: TimeoutError, ConnectionError, or HTTPError 503
   - Return error_type=TRANSIENT
3. If success (70% of time) → return mock verification:
   - is_active: bool (random, 80% true)
   - verified_discount: str
   - verified_expiry: str

This tool MUST be retried with backoff by the agent.
The agent MUST NOT crash when this fails.
The 30% failure rate is intentional and documented.

Output Schema:
- is_active: bool | None
- verified_discount: str | None
- verified_expiry: str | None
- verification_source: str = "mock_verifier_v1"
```

---

### `agent/budget.py`
```
Class: BudgetEnforcer

Tracks all resource consumption and enforces hard limits.

Limits (loaded from .env):
- MAX_TOKENS_PER_RUN: default 150,000
- MAX_WALL_CLOCK_SECONDS: default 900 (15 minutes)
- MAX_TOOL_CALLS: default 200
- MAX_CONSECUTIVE_FAILURES: default 5

Methods:
- record_tokens(count: int, provider: str)
- record_tool_call(tool_name: str, success: bool)
- record_failure() / record_success()  ← resets consecutive counter on success
- check_limits() → returns BudgetStatus(ok: bool, reason: str | None, report: dict)
- get_report() → full usage report with % of each limit consumed

BudgetStatus must be checked:
- After EVERY tool call
- After EVERY LLM call
- At the start of EVERY new merchant

If any limit breached:
- Set state.budget_exceeded = True
- Generate partial report with completed vs remaining merchants
- Halt immediately (raise BudgetExceededError)
```

---

### `agent/planner.py`
```
Class: AgentPlanner

Uses LLM to decide the plan for each merchant.

Input: merchant info + available tools from registry + current state

Prompt:
"""
You are an agent planner for GrabOn's deal audit system.

Merchant: {merchant_name}
URL: {merchant_url}
Available tools: {tool_list_from_registry}
Current budget used: {tokens_used}/{max_tokens} tokens, {tool_calls}/{max_tool_calls} calls

Create a step-by-step plan to:
1. Scrape this merchant's deal page
2. Extract deals
3. Compare with our database
4. Classify each deal

Return ONLY JSON:
{
  "steps": [
    {"step": 1, "tool": "scrape_html", "reason": "Start with direct HTTP scrape"},
    {"step": 2, "tool": "extract_deals", "reason": "Parse HTML for coupon codes"},
    {"step": 3, "tool": "db_lookup", "reason": "Get internal DB records"},
    {"step": 4, "tool": "classify_deals", "reason": "Compare and classify"}
  ],
  "fallback_if_scrape_fails": "google_cache",
  "estimated_tool_calls": 4
}
"""

The planner must also handle RE-PLANNING when a tool fails persistently.
Re-plan prompt adds: "Tool {tool_name} failed with {error_type}. 
{TRANSIENT → retry with backoff} {PERMANENT/RATE_LIMIT → use alternative tool}"
```

---

### `agent/loop.py` ← MOST IMPORTANT FILE
```
Class: AgentLoop

This is the core. Every evaluator will look at this file first.

The loop must have EXPLICIT phases — not implicit:

```python
class Phase(str, Enum):
    PLAN = "PLAN"
    ACT = "ACT"
    OBSERVE = "OBSERVE"
    DECIDE = "DECIDE"
```

Main method: `async def run(merchants: list[dict]) -> AgentState`

For each merchant, the loop runs:

--- PHASE 1: PLAN ---
- Call AgentPlanner.create_plan(merchant)
- Log: step_number, phase=PLAN, action="Created plan", decision=plan summary
- Record iteration in state

--- PHASE 2: ACT ---
- Execute the planned tool from registry
- Apply timeout from tool definition
- Log: phase=ACT, tool_called=tool_name, action=params sent

--- PHASE 3: OBSERVE ---
- Receive ToolResult from registry
- Record: success/failure, latency, error_type if failed
- Log: phase=OBSERVE, observation=result summary

--- PHASE 4: DECIDE ---
This is the most complex phase. Logic:

```
if result.success:
    if more_steps_in_plan:
        decision = "CONTINUE to next step"
    else:
        decision = "MERCHANT COMPLETE"
        
elif result.error_type == "TRANSIENT":
    if retry_count < 3:
        decision = "RETRY with exponential backoff"
        wait = 2 ** retry_count  # 2s, 4s, 8s
    else:
        decision = "ESCALATE to alternative tool"
        
elif result.error_type == "RATE_LIMIT":
    decision = "WAIT 30s then RETRY"
    
elif result.error_type == "NOT_FOUND":
    decision = "PAGE NOT FOUND — try google_cache"
    
elif result.error_type == "PERMANENT":
    decision = "REPLAN with alternative tool"
    call AgentPlanner.replan(merchant, failed_tool, error)
    
elif result.error_type == "TIMEOUT":
    if tool == "scrape_html":
        decision = "SWITCH to scrape_js (slower but more reliable)"
    else:
        decision = "GRACEFUL DEGRADATION — partial result"
```

- Log: phase=DECIDE, decision=above, reasoning=why

--- AFTER ALL MERCHANTS ---
- Generate final audit report
- Save to reports/audit_{timestamp}.json
- Display summary in Rich terminal

Iteration logging (EVERY iteration):
```python
iteration = AgentIteration(
    step_number=step,
    phase=current_phase,
    action=action_taken,
    tool_called=tool_name,
    observation=result_summary,
    decision=decision_made,
    tokens_consumed=tokens_this_step,
    wall_clock_time=time.time() - step_start,
    llm_provider=provider_used,
    cost_usd=cost_this_step
)
state.iterations.append(iteration)
```

Budget check after EVERY iteration:
```python
budget_status = budget_enforcer.check_limits()
if not budget_status.ok:
    raise BudgetExceededError(budget_status.reason)
```
```

---

### `observability/terminal_ui.py`
```
Use Rich library for a live terminal dashboard.

Layout (use Rich Layout + Live):

┌─────────────────────────────────────────────────────────┐
│  🤖 GrabOn Deal Audit Agent — LIVE                     │
│  Session: abc123  |  Started: 14:32:01                  │
├─────────────────────────────────────────────────────────┤
│  CURRENT MERCHANT: Myntra [7/20]                        │
│  Phase: OBSERVE  |  Tool: extract_deals                 │
│  Step: 3  |  Elapsed: 2m 14s                           │
├────────────────────────────┬────────────────────────────┤
│  MERCHANT PROGRESS         │  TOKEN USAGE               │
│  ✅ Amazon   — Fresh       │  ████████░░░░  62,400      │
│  ✅ Flipkart — Fresh       │  Limit: 150,000            │
│  ⚠️ Zomato   — Stale       │                            │
│  ✅ Swiggy   — Fresh       │  TOOL CALLS                │
│  ❌ MakeMyTrip — Error     │  ████░░░░░░░░  84/200      │
│  🔄 Myntra   — In Progress │                            │
│  ⏳ Nykaa    — Pending     │  COST SO FAR               │
│                            │  $0.0023                   │
├────────────────────────────┴────────────────────────────┤
│  LAST TOOL CALL: extract_deals → SUCCESS (1.2s)        │
│  AGENT DECISION: Continue to classify_deals            │
│  PROVIDER: Gemini Flash | Tokens: 1,847 | $0.0001      │
├─────────────────────────────────────────────────────────┤
│  RECENT ITERATIONS                                      │
│  Step 12 | PLAN  | Created plan for Myntra             │
│  Step 13 | ACT   | Called scrape_html                  │
│  Step 14 | OBSERVE | Got 200 OK, 45KB HTML             │
│  Step 15 | DECIDE | Continue — HTML looks valid        │
└─────────────────────────────────────────────────────────┘

Update the dashboard after every iteration (use Rich Live context manager).
```

---

### `observability/langsmith_tracer.py`
```
Wrap the entire agent session in a LangSmith trace.

What to trace:
- Parent run: Full audit session (all 20 merchants)
- Child run per merchant: Each merchant's full loop
- Grandchild runs: Each individual tool call

Tag every trace with:
- merchant_id
- tool_name  
- phase (PLAN/ACT/OBSERVE/DECIDE)
- llm_provider
- tokens_used
- cost_usd
- decision_made
- error_type (if failed)

Use langsmith.traceable decorator on:
- AgentLoop.run()
- AgentLoop._run_merchant()
- Each tool's execute() function
- LLMRouter.call_with_tracking()

This gives the interviewer a full trace they can view at smith.langchain.com
```

---

## 🧪 Step 6 — Eval Suite (`evals/scenarios.py`)

Define 30 test scenarios. Each scenario is a dict:
```python
{
    "id": "TC001",
    "name": "Happy path - Amazon fresh deal",
    "category": "happy_path",
    "merchant_id": "amazon",
    "mock_scrape_response": {...},  # what the scraper returns
    "mock_db_response": {...},       # what DB returns
    "expected_classification": "FRESH",
    "expected_agent_decision": "CONTINUE",
    "should_call_fallback": False
}
```

### The 30 Scenarios:

**Happy Path (10 scenarios):**
- TC001: Amazon — deal matches exactly → FRESH
- TC002: Flipkart — deal on page, not in DB → EXTRA (new deal)
- TC003: Swiggy — all 3 deals match → all FRESH
- TC004: boAt — deal found, minor description change → FRESH (ignore description)
- TC005: Domino's — deal found, discount matches, not expired → FRESH
- TC006: Nykaa — 2 fresh, 1 extra deal on page
- TC007: BigBasket — no deals on page, no deals in DB → clean merchant
- TC008: CRED — deal found with exact match
- TC009: Tata CLiQ — deal found, different min_order but same discount → FRESH
- TC010: Netmeds — 3 deals all matching → all FRESH

**Failure and Recovery (8 scenarios):**
- TC011: Myntra — scrape_html returns 403 → agent switches to google_cache → success
- TC012: Zomato — scrape_html times out → agent switches to scrape_js → success
- TC013: MakeMyTrip — JS scraper also fails → graceful degradation → UNKNOWN status
- TC014: unreliable_verifier fails 3 times → agent retries with backoff → eventually succeeds
- TC015: deal_extractor LLM returns malformed JSON → agent retries with different prompt
- TC016: google_cache also blocked → agent marks merchant ERROR and continues to next
- TC017: DB lookup returns empty → agent still runs live comparison → EXTRA for all live deals
- TC018: Scrape returns empty HTML → agent re-plans → tries scrape_js → succeeds

**Budget Exceeded (4 scenarios):**
- TC019: max_tool_calls=5, task needs 15 → halts after 5, partial report generated
- TC020: max_tokens=1000, normal task → halts mid-merchant, report shows completed/remaining
- TC021: max_wall_clock=10s, normal task → time limit breach, clean halt
- TC022: max_consecutive_failures=2 → 3rd failure triggers halt

**Impossible / Edge Cases (4 scenarios):**
- TC023: Merchant URL returns 404 permanently → agent detects NOT_FOUND, skips, does not loop
- TC024: All tools blocked for one merchant → agent marks ERROR after max retries, moves on
- TC025: LLM returns coupon codes that don't appear in HTML → agent flags as hallucination (low confidence score < 0.3)
- TC026: Merchant has 0 deals on page AND 0 in DB → agent classifies as CLEAN, not an error

**Multi-LLM Specific (4 scenarios):**
- TC027: Groq rate limit → planner falls back to OpenRouter
- TC028: Gemini Flash error → deal extraction falls back to Groq
- TC029: Verify cost tracking works — check $0 for mock calls
- TC030: Provider selection — confirm cheap model used for classification

---

## 📊 Step 7 — Final Audit Report Format

Save to `reports/audit_{session_id}_{timestamp}.json`:

```json
{
  "session_id": "abc123",
  "generated_at": "2025-01-15T14:47:23Z",
  "duration_seconds": 743,
  "total_merchants": 20,
  "completed": 18,
  "failed": 2,
  "budget_exceeded": false,
  
  "summary": {
    "total_deals_audited": 47,
    "fresh": 28,
    "stale": 8,
    "missing": 6,
    "updated": 3,
    "extra": 2,
    "unknown": 0
  },
  
  "cost_breakdown": {
    "total_usd": 0.0047,
    "by_provider": {
      "groq": {"tokens": 45000, "cost_usd": 0.0023},
      "gemini_flash": {"tokens": 38000, "cost_usd": 0.0019},
      "openrouter": {"tokens": 12000, "cost_usd": 0.0005},
      "nvidia": {"tokens": 0, "cost_usd": 0.0}
    },
    "by_task_type": {
      "planning": {"tokens": 18000, "cost_usd": 0.0009},
      "extraction": {"tokens": 52000, "cost_usd": 0.0026},
      "classification": {"tokens": 25000, "cost_usd": 0.0012}
    }
  },
  
  "tool_call_stats": {
    "total_calls": 94,
    "by_tool": {
      "scrape_html": {"calls": 20, "success": 16, "failed": 4},
      "google_cache": {"calls": 4, "success": 3, "failed": 1},
      "scrape_js": {"calls": 1, "success": 1, "failed": 0},
      "extract_deals": {"calls": 20, "success": 20, "failed": 0},
      "db_lookup": {"calls": 20, "success": 20, "failed": 0},
      "classify_deals": {"calls": 20, "success": 20, "failed": 0},
      "verify_coupon": {"calls": 9, "success": 7, "failed": 2}
    }
  },
  
  "merchants": [
    {
      "merchant_id": "amazon",
      "name": "Amazon",
      "status": "completed",
      "health_score": 1.0,
      "deals": [
        {
          "code": "AMZNEW10",
          "db_discount": "10%",
          "live_discount": "10%",
          "classification": "FRESH",
          "expiry": "2025-12-31",
          "expired": false
        }
      ],
      "tool_calls_used": 5,
      "time_taken_seconds": 34.2,
      "fallback_used": false
    }
  ],
  
  "iterations_log": [
    {
      "step": 1, "phase": "PLAN", "merchant": "amazon",
      "action": "Created 4-step plan", "tool_called": null,
      "observation": "Plan ready", "decision": "Execute step 1: scrape_html",
      "tokens": 847, "cost_usd": 0.000042, "provider": "groq",
      "wall_clock_seconds": 1.23
    }
  ],
  
  "recovery_events": [
    {
      "merchant": "myntra",
      "step": 8,
      "error": "403 Forbidden on scrape_html",
      "error_type": "RATE_LIMIT",
      "recovery_action": "Switched to google_cache",
      "recovery_success": true
    }
  ]
}
```

---

## 🚀 Step 8 — `main.py` Entry Point

```python
"""
GrabOn Merchant Deal Audit Agent — Entry Point

Usage:
    python main.py                    # Run full audit (all 20 merchants)
    python main.py --merchants 5      # Run first 5 merchants only
    python main.py --eval             # Run eval suite instead
    python main.py --merchant amazon  # Run single merchant
"""

import asyncio
import argparse
import json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from agent.loop import AgentLoop
from observability.terminal_ui import TerminalUI
from evals.runner import EvalRunner

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--merchants", type=int, default=20)
    parser.add_argument("--merchant", type=str, default=None)
    parser.add_argument("--eval", action="store_true")
    args = parser.parse_args()
    
    if args.eval:
        runner = EvalRunner()
        results = await runner.run_all()
        runner.print_summary(results)
        return
    
    merchants = json.loads(Path("data/merchants.json").read_text())
    
    if args.merchant:
        merchants = [m for m in merchants if m["id"] == args.merchant]
    else:
        merchants = merchants[:args.merchants]
    
    ui = TerminalUI()
    loop = AgentLoop(ui=ui)
    
    with ui.live_context():
        state = await loop.run(merchants)
    
    # Save report
    report_path = f"reports/audit_{state.session_id}.json"
    Path("reports").mkdir(exist_ok=True)
    Path(report_path).write_text(json.dumps(state.final_report, indent=2))
    
    print(f"\n✅ Audit complete. Report saved: {report_path}")
    print(f"💰 Total cost: ${state.total_cost_usd:.4f}")
    print(f"🔢 Total tokens: {state.total_tokens:,}")

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 📖 Step 9 — README.md Structure (Architecture Doc)

The README must include:

1. **Architecture Diagram** (ASCII or Mermaid) showing:
   - Agent Loop → Tool Registry → Individual Tools → LLM Router → Providers
   
2. **Why each LLM was chosen for each task** (justify every routing decision)

3. **Tool Registry Design** — how tools are discovered dynamically

4. **Failure Recovery Decision Tree** — show the DECIDE phase logic visually

5. **LangSmith Setup** — how to view traces

6. **What Broke First** — honest section about first failure encountered

7. **What I'd Change with More Time** — shows engineering maturity

8. **Live vs Mocked** — clear table of what makes real API calls

9. **Setup Instructions** — must work in under 15 minutes on Windows

10. **Eval Results** — show the 30 scenario pass/fail table

---

## ⚡ Setup Commands (Windows)

```bash
# 1. Clone and enter
cd grabon-audit-agent

# 2. Create virtual environment
python -m venv venv
venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Install Playwright browsers
playwright install chromium

# 5. Copy and fill env
copy .env.example .env
# → Fill in your API keys

# 6. Run the agent
python main.py --merchants 5

# 7. Run evals
python main.py --eval

# 8. View LangSmith traces at: https://smith.langchain.com
```

---

## 🎯 What the Interviewer Will Test — Be Prepared

| Test | What to Say |
|---|---|
| "Disable a tool mid-run" | Registry marks tool as unavailable, Planner re-plans on next DECIDE phase |
| "Set max_tool_calls=3" | BudgetEnforcer catches it after 3rd call, raises BudgetExceededError, partial report generated |
| "Why Google Cache at step 7?" | Check iterations_log — DECIDE phase reasoning explains: "scrape_html returned 403 RATE_LIMIT → policy: try google_cache before escalating" |
| "Add a new tool" | Create file in tools/, add @registry.register decorator, restart — it's auto-discovered |
| "What does LangGraph add?" | State management, conditional edges for DECIDE branching, built-in retry nodes |

---

## ✅ Final Checklist Before Submission

- [ ] `AgentLoop` class exists with explicit `Phase` enum (PLAN/ACT/OBSERVE/DECIDE)
- [ ] 7 tools registered in ToolRegistry with Pydantic schemas
- [ ] `unreliable_verifier` fails 30% of the time
- [ ] BudgetEnforcer halts the agent on any limit breach
- [ ] At least 3 failure recovery strategies implemented
- [ ] 30 eval scenarios run via `python main.py --eval`
- [ ] LangSmith traces visible at smith.langchain.com
- [ ] Rich terminal shows live agent state
- [ ] Scraped HTML saved to `data/scraped/`
- [ ] Final report saved to `reports/`
- [ ] 4 LLM providers configured (Groq, Gemini, OpenRouter, Nvidia)
- [ ] Cost tracked per call per provider
- [ ] README has architecture diagram + tradeoffs + what broke
- [ ] `git clone` → running in under 15 minutes on Windows
- [ ] Loom video with audio walking through the architecture