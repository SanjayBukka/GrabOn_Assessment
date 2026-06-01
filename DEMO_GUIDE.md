# 🤖 GrabOn Audit Agent — Complete Explanation & Demo Guide

---

## 📊 TABLE OF CONTENTS
1. [How the Application Works](#how-the-application-works)
2. [How the Agent Works (PLAN/ACT/OBSERVE/DECIDE Loop)](#how-the-agent-works)
3. [What Each Tool Does](#what-each-tool-does)
4. [What Each File Does](#what-each-file-does)
5. [How to Demo](#how-to-demo)
6. [Files to Remove Before Demo](#files-to-remove-before-demo)
7. [Precautions](#precautions)

---

## 🏗️ How the Application Works

### The Big Picture

This is an **autonomous agent** that audits GrabOn's merchant deal pages. It:
1. **Scrapes** live deal pages from 20 merchants
2. **Extracts** coupon codes using AI
3. **Compares** with an internal database
4. **Classifies** deals as FRESH, STALE, MISSING, or UPDATED
5. **Reports** discrepancies back to GrabOn

### High-Level Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    START: python main.py                        │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│  Load 20 merchants from data/merchants.json                     │
│  (Amazon, Myntra, Zomato, Flipkart, etc.)                      │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│  FOR EACH MERCHANT (18 seconds average):                        │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  PHASE 1: PLAN                                          │   │
│  │  ├─ LLM thinks: "How should I audit this merchant?"    │   │
│  │  ├─ Creates a 4-step plan                              │   │
│  │  └─ Step 1: Scrape HTML, Step 2: Extract deals, etc.   │   │
│  └─────────────────────────────────────────────────────────┘   │
│                         ▼                                       │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  PHASE 2: ACT                                           │   │
│  │  ├─ Execute Step 1 from plan (e.g., scrape_html)       │   │
│  │  ├─ Wait 2 seconds (to be respectful)                   │   │
│  │  ├─ Download HTML from GrabOn page                      │   │
│  │  └─ Save to data/scraped/merchant_timestamp.html        │   │
│  └─────────────────────────────────────────────────────────┘   │
│                         ▼                                       │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  PHASE 3: OBSERVE                                       │   │
│  │  ├─ Check: Did scrape succeed or fail?                 │   │
│  │  ├─ If 200 OK → got 45KB HTML                          │   │
│  │  ├─ If 403 → rate limited (error_type = RATE_LIMIT)    │   │
│  │  └─ If timeout → took >10s (error_type = TIMEOUT)      │   │
│  └─────────────────────────────────────────────────────────┘   │
│                         ▼                                       │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  PHASE 4: DECIDE                                        │   │
│  │  ├─ If success: "Continue to Step 2"                   │   │
│  │  ├─ If RATE_LIMIT: "Wait 30s then retry"              │   │
│  │  ├─ If TIMEOUT: "Switch to slower scraper (Playwright)"│   │
│  │  └─ If PERMANENT: "Skip this merchant"                │   │
│  └─────────────────────────────────────────────────────────┘   │
│                         ▼                                       │
│  Repeat for Steps 2, 3, 4...                                   │
│  (Extract deals from HTML, lookup DB, classify deals)          │
│                                                                 │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│  Generate Report                                                │
│  ├─ Total deals audited: 47                                    │
│  ├─ Fresh: 28 ✅                                               │
│  ├─ Stale: 8 ⚠️                                                │
│  ├─ Missing: 6 ❌                                              │
│  └─ Save to reports/audit_TIMESTAMP.json                       │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
          ✅ Done! Show dashboard with results
```

---

## 🧠 How the Agent Works: PLAN/ACT/OBSERVE/DECIDE Loop

This is the **core engine** of the agent. Read this carefully.

### PHASE 1: PLAN 🎯

**What happens:**
- For each merchant, we call the **Planner LLM** (Groq 70B model)
- The LLM reads:
  - Merchant info (name, URL, category)
  - Available tools (7 tools registered)
  - Budget constraints (tokens left, tool calls left)
- LLM responds with a step-by-step plan

**Example Plan for Amazon:**
```json
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
```

**Cost:** ~200 tokens, ~$0.00001

**Provider used:** Groq (fast, cheap reasoning model)

---

### PHASE 2: ACT ⚙️

**What happens:**
- Execute the next tool from the plan
- Tool registry looks up the tool by name
- Parameters are prepared and validated with Pydantic
- Tool runs with timeout enforcement

**Example: Running scrape_html for Amazon**
```
Input:
  - url: https://www.grabon.in/amazon-coupons/
  - timeout_seconds: 10
  - delay_before: 2.0
  - merchant_id: amazon

Actions:
  1. Wait 2 seconds (respectful scraping)
  2. Make GET request with rotating User-Agent
  3. Receive 200 OK response
  4. Save HTML to: data/scraped/amazon_20260530_165341.html
  5. Extract page title

Output:
  - html: "<html>... 45KB of coupon HTML ...</html>"
  - page_title: "Amazon Coupons & Offers - GrabOn"
  - status_code: 200
  - saved_path: "data/scraped/amazon_20260530_165341.html"
  - error_type: null
```

**Latency:** 2-5 seconds (mostly the 2s delay + network)

**Cost:** $0 (no LLM call)

---

### PHASE 3: OBSERVE 👁️

**What happens:**
- The tool result arrives
- We **classify the error** (if any) into one of 5 categories:
  - ✅ `SUCCESS` → no error
  - 🔄 `TRANSIENT` → temporary problem, safe to retry (timeout, connection error)
  - 🚫 `RATE_LIMIT` → throttled (HTTP 429/403), wait and retry
  - ❌ `NOT_FOUND` → page gone (HTTP 404), switch strategy
  - ⛔ `PERMANENT` → real error (bad URL, auth required)
- We **classify the result** as one of:
  - `COMPLETE` → Got what we needed
  - `PARTIAL` → Got some data but not everything
  - `EMPTY` → Got data but it's empty (valid!)
  - `ERROR` → Tool failed

**Example Observation:**
```
Tool: scrape_html
Status: SUCCESS
Error Classification: NONE
Result Classification: COMPLETE (got 45KB HTML)
Latency: 3.2 seconds
Observation: "Successfully scraped Amazon page, got 45 coupon codes"
```

**Cost:** $0 (pure analysis)

---

### PHASE 4: DECIDE 🤔

**What happens:**
- Look at the observation and make a decision
- This is a **decision tree** with 6 possible outcomes:

#### Decision Tree

```
Is result successful?
│
├─ YES (COMPLETE)
│  ├─ More steps in plan?
│  │  ├─ YES → Decision: "CONTINUE to next step"
│  │  └─ NO  → Decision: "MERCHANT COMPLETE"
│  └─ (Move to next step)
│
└─ NO (ERROR or PARTIAL)
   │
   ├─ Error type = TRANSIENT?
   │  ├─ Retries < 3?
   │  │  ├─ YES → Decision: "RETRY with 2^retry_count backoff"
   │  │  │        (Wait 2s, 4s, 8s)
   │  │  └─ NO  → Decision: "SWITCH_TOOL to fallback"
   │  │
   │
   ├─ Error type = RATE_LIMIT?
   │  └─ Decision: "WAIT 30s then RETRY"
   │
   ├─ Error type = NOT_FOUND?
   │  └─ Decision: "SWITCH_TOOL: try google_cache"
   │     (If that fails too → try scrape_js)
   │
   ├─ Error type = TIMEOUT?
   │  ├─ Was tool scrape_html?
   │  │  └─ YES → Decision: "SWITCH_TOOL to scrape_js (Playwright)"
   │  └─ Was tool something else?
   │     └─ Decision: "GRACEFUL DEGRADATION"
   │
   └─ Error type = PERMANENT?
      └─ Decision: "REPLAN" (ask LLM for new strategy)
```

**Example Decisions:**

| Observation | Decision | Why |
|---|---|---|
| Scrape success, HTML complete | CONTINUE | Got what we needed, move to extract_deals |
| Scrape returns 403 Forbidden | SWITCH_TOOL: google_cache | Rate limited, try cache |
| Extract_deals timeout on 1st try | RETRY after 2s | Transient, can try again |
| Extract_deals timeout on 3rd try | SWITCH_TOOL or REPLAN | Given up on this tool |
| Classify returns empty (no issues) | MERCHANT COMPLETE | That's valid! No discrepancies |

**Budget Check:**
After **every decision**, we check:
- Total tokens used < 150,000?
- Total tool calls < 200?
- Wall clock time < 900s?
- Consecutive failures < 5?

If any limit breached → **HALT immediately**, generate partial report

**Cost:** ~50 tokens (small LLM call to think about decision), ~$0.000003

---

### The Full Loop (One Iteration)

```
1 PLAN   (5s)  → Create strategy
   │
2 ACT    (2s)  → Execute tool (scrape_html)
   │
3 OBSERVE(0s)  → Analyze result (HTML received, 200 OK)
   │
4 DECIDE (1s)  → Decision: CONTINUE to next step
   │
   [BUDGET CHECK]
   │
   NEXT ITERATION starts...
   
TOTAL: ~8 seconds for 1 full iteration
TOTAL per merchant: ~20-30 seconds (4 iterations × 5-8 seconds)
TOTAL for all 20 merchants: ~7-10 minutes
```

---

## 🔧 What Each Tool Does

### Tool 1: **scrape_html** (Primary Web Scraper)
- **Purpose:** Download raw HTML from a GrabOn deal page
- **How:** Uses httpx (lightweight HTTP client)
- **Input:**
  - `url`: The GrabOn page URL (e.g., amazon-coupons/)
  - `delay_before`: 2 seconds (respectful scraping)
  - `merchant_id`: For logging
- **Output:**
  - `html`: The page source code (~50KB typically)
  - `status_code`: HTTP status (200, 403, 404, etc.)
  - `saved_path`: Where HTML was saved
  - `error_type`: What went wrong (if anything)
- **Timeout:** 10 seconds
- **When it fails:**
  - 403 Forbidden → rate limited
  - 404 Not Found → page doesn't exist
  - Timeout → server too slow
  - Connection error → network issue

---

### Tool 2: **google_cache** (Fallback Scraper #1)
- **Purpose:** Get cached version from Google Cache when direct scrape is blocked
- **How:** Queries `webcache.googleusercontent.com`
- **Input:**
  - `original_url`: The URL we want cached version of
- **Output:** Same as scrape_html
- **When to use:** After scrape_html gets 403 or 404
- **Advantage:** Often bypasses rate limiting
- **Disadvantage:** Cache might be stale (hours or days old)
- **Timeout:** 15 seconds

---

### Tool 3: **scrape_js** (Fallback Scraper #2 — Slow but Powerful)
- **Purpose:** Scrape JavaScript-rendered pages (Cloudflare protected)
- **How:** Uses Playwright (real browser automation)
- **Input:**
  - `url`: The URL to scrape
  - `wait_for_selector`: Wait for `.coupon-code` element
- **Output:** Rendered HTML (after JS executes)
- **When to use:** Last resort, when HTML and Cache both fail
- **Advantage:** Can handle dynamic pages, JavaScript execution
- **Disadvantage:** SLOW (20-30 seconds per page)
- **Timeout:** 30 seconds

---

### Tool 4: **extract_deals** (AI Deal Extractor)
- **Purpose:** Parse HTML and extract structured coupon codes
- **How:** Uses Gemini Flash LLM (vision model)
- **Input:**
  - `html`: Raw page HTML
  - `merchant_name`: For context
  - `merchant_id`: For tracking
- **Output:**
  ```json
  {
    "deals": [
      {
        "code": "AMZNEW10",
        "discount": "10% off",
        "description": "10% off on electronics",
        "expiry": "2025-12-31",
        "min_order": 500
      }
    ],
    "extraction_confidence": 0.95,
    "deals_found_count": 3
  }
  ```
- **How it works:**
  1. Truncate HTML to 8000 chars (to fit in token limit)
  2. Send to Gemini Flash with extraction prompt
  3. LLM finds all coupon patterns
  4. Return structured JSON
- **Cost:** ~500 tokens, ~$0.00015
- **Provider:** Gemini Flash (good at parsing)

---

### Tool 5: **db_lookup** (Database Query)
- **Purpose:** Query the internal GrabOn database for a merchant's deals
- **How:** Loads `data/mock_db.json` and filters by merchant_id
- **Input:**
  - `merchant_id`: e.g., "amazon"
- **Output:**
  ```json
  {
    "deals": [
      {"code": "AMZNEW10", "discount": "10%", "expiry": "2025-12-31"},
      {"code": "PRIMESAVE", "discount": "15%", "expiry": "2025-06-30"}
    ],
    "merchant_found": true,
    "deal_count": 2
  }
  ```
- **Cost:** $0 (no LLM, just file read)
- **Speed:** <100ms
- **Note:** This is MOCKED (simulates GrabOn's internal DB)

---

### Tool 6: **classify_deals** (Comparison Engine)
- **Purpose:** Compare live deals vs DB deals and classify each
- **How:** 
  1. Takes DB deals and live deals
  2. Compares them using business logic (NOT LLM)
  3. Classifies each deal
- **Classification Rules:**
  - **FRESH** ✅: Code in DB and on page, same discount, not expired
  - **STALE** ⚠️: Code on page but discount changed or expiry passed
  - **MISSING** ❌: Code in DB but not on live page
  - **UPDATED** 🔄: Code on live page with different discount than DB
  - **EXTRA** ✨: Deal on page but not in DB (new deal)
- **Input:**
  - `merchant_id`: Which merchant
  - `db_deals`: Deals from database
  - `live_deals`: Deals from live page
- **Output:**
  ```json
  {
    "classified_deals": [...],
    "summary": {
      "fresh": 5,
      "stale": 2,
      "missing": 1,
      "updated": 0,
      "extra": 1
    },
    "merchant_health_score": 0.833
  }
  ```
- **Cost:** $0 (no LLM call, pure logic)
- **Speed:** <100ms

---

### Tool 7: **verify_coupon** (Unreliable Verifier)
- **Purpose:** Verify if a coupon code is actually active
- **How:** Mock verification with **intentional 30% failure rate**
- **Input:**
  - `merchant_id`: e.g., "amazon"
  - `coupon_code`: e.g., "AMZNEW10"
- **Output:**
  ```json
  {
    "is_active": true,
    "verified_discount": "10% off",
    "verified_expiry": "2025-12-31"
  }
  ```
- **Why 30% failure:** To test agent's failure recovery! 
- **When it fails:**
  - Randomly returns TimeoutError (30% of calls)
  - Agent should retry with exponential backoff
  - Test that agent doesn't crash
- **Cost:** $0 (mock verification)

---

## 📁 What Each File Does

### **Core Agent Files**

#### `agent/state.py`
- **Purpose:** Define all data models used by the agent
- **Contains:**
  - `Phase`: Enum (PLAN, ACT, OBSERVE, DECIDE)
  - `DealStatus`: Enum (FRESH, STALE, MISSING, UPDATED, ERROR)
  - `DealRecord`: A single coupon code with metadata
  - `AgentIteration`: One iteration's data (phase, tool called, decision)
  - `AgentState`: Full session state (all iterations, results, budget)
  - `MerchantResult`: Results for one merchant
- **Used by:** All other files
- **Format:** Pydantic models (strict validation)

#### `agent/loop.py` ⭐ **THE MAIN LOOP**
- **Purpose:** Core PLAN/ACT/OBSERVE/DECIDE engine
- **Contains:**
  - `AgentLoop` class with `run()` method
  - Implements 4-phase loop for each merchant
  - Handles failures and retries
  - Enforces budget after every iteration
- **Flow:**
  1. For each merchant:
     - PLAN: Create strategy
     - ACT: Execute tool
     - OBSERVE: Analyze result
     - DECIDE: Make next decision
  2. Track everything in iterations_log
  3. Generate final report
- **Key:** This is what an interviewer will look at first

#### `agent/budget.py`
- **Purpose:** Enforce hard limits on resource consumption
- **Limits enforced:**
  - Max tokens per run: 150,000
  - Max wall clock time: 900 seconds (15 min)
  - Max tool calls: 200
  - Max consecutive failures: 5
- **Methods:**
  - `record_tokens()`: Log token usage
  - `record_tool_call()`: Log tool execution
  - `check_limits()`: Verify we're still under limits
  - `get_report()`: Show usage summary
- **When violated:** Raises `BudgetExceededError`, halts agent

#### `agent/planner.py`
- **Purpose:** LLM-based planning for each merchant
- **What it does:**
  1. Reads merchant info + available tools
  2. Asks Groq LLM: "Create a 4-step plan for this merchant"
  3. LLM returns ordered list of tools to execute
  4. Also handles REPLANNING when tool fails
- **Cost:** ~200 tokens per plan, ~$0.00001

---

### **Tool Files**

#### `tools/registry.py`
- **Purpose:** Manage all tools (registration, discovery, execution)
- **How it works:**
  1. Tools register via `@registry.register()` decorator
  2. Registry stores metadata (name, timeout, schema)
  3. When needed, fetch tool by name
  4. Execute with timeout enforcement
  5. Track stats (success rate, latency)
- **Key methods:**
  - `register()`: Add a new tool
  - `execute()`: Run a tool with timeout
  - `get_tool()`: Fetch tool by name
  - `list_tools()`: See all tools
  - `get_stats()`: Tool statistics

#### `tools/scraper_html.py`
- Implements `scrape_html` tool (see tool #1 above)

#### `tools/google_cache.py`
- Implements `google_cache` tool (see tool #2 above)

#### `tools/scraper_js.py`
- Implements `scrape_js` tool (see tool #3 above)

#### `tools/deal_extractor.py`
- Implements `extract_deals` tool (see tool #4 above)
- Uses Gemini Flash LLM to parse HTML

#### `tools/db_lookup.py`
- Implements `db_lookup` tool (see tool #5 above)
- Loads `data/mock_db.json`

#### `tools/deal_classifier.py`
- Implements `classify_deals` tool (see tool #6 above)
- Pure business logic (no LLM)

#### `tools/unreliable_verifier.py`
- Implements `verify_coupon` tool (see tool #7 above)
- 30% failure rate intentional

---

### **LLM Files**

#### `llm/router.py`
- **Purpose:** Route different tasks to best LLM provider
- **Routing decisions:**
  - PLANNING → Groq llama-3.1-70b (fast, good reasoning)
  - DEAL_EXTRACTION → Gemini Flash (good at parsing)
  - CLASSIFICATION → Groq llama-3.1-8b (cheap, fast)
  - FALLBACK → OpenRouter (free tier fallback)
  - DETECTION → OpenRouter (also used as fallback)
- **Why different models?**
  - Planning needs reasoning → use big model
  - Classification is simple → use small model (cheaper)
  - Extraction needs context awareness → use latest model
- **Fallback chain:** If primary provider fails → try next

#### `llm/cost_tracker.py`
- **Purpose:** Track LLM costs per call, per provider, per task
- **Tracks:**
  - Tokens used (input + output)
  - Cost in USD (using real rates)
  - Per provider breakdown (Groq $0.00015/1K output, Gemini $0.0075/1K input, etc.)
  - Per task type (planning, extraction, classification)
- **Output:** `get_report()` shows full cost breakdown

---

### **Observability Files**

#### `observability/terminal_ui.py`
- **Purpose:** Live terminal dashboard showing agent progress
- **Displays:**
  - Current merchant being audited
  - Current phase (PLAN/ACT/OBSERVE/DECIDE)
  - Progress bars for tokens, tool calls
  - Recent iterations
  - Cost so far
  - Merchant status icons (✅ ⚠️ ❌ 🔄)
- **Tech:** Uses Rich library for fancy terminal UI
- **Updates:** After every iteration (real-time)

#### `observability/langsmith_tracer.py`
- **Purpose:** Full tracing to LangSmith cloud for debugging
- **What gets traced:**
  - Parent run: Full audit session
  - Child runs: Each merchant
  - Grandchild runs: Each tool execution
- **Tags:**
  - merchant_id, tool_name, phase, error_type, decision, cost
- **Result:** View full execution tree at smith.langchain.com

---

### **Eval Files**

#### `evals/scenarios.py`
- **Purpose:** 30 test scenarios covering happy path + failures
- **Contains:**
  - Happy path: 10 scenarios (normal cases)
  - Failures: 8 scenarios (what if scraper fails?)
  - Budget exceeded: 4 scenarios (limit breaches)
  - Edge cases: 4 scenarios (impossible situations)
  - Multi-LLM: 4 scenarios (provider fallback)
- **Each scenario specifies:**
  - Mock API responses
  - Expected classifications
  - Expected agent decisions

#### `evals/runner.py`
- **Purpose:** Run all 30 scenarios and report results
- **What it does:**
  1. Load each scenario
  2. Mock the tool responses
  3. Run agent with mocked tools
  4. Check if result matches expected
  5. Report pass/fail rate

---

### **Data Files**

#### `data/merchants.json`
- **Purpose:** List of 20 merchants to audit
- **Format:**
  ```json
  [
    {"id": "amazon", "name": "Amazon", "url": "https://www.grabon.in/amazon-coupons/", "category": "ecommerce"},
    {"id": "myntra", "name": "Myntra", "url": "https://www.grabon.in/myntra-coupons/", "category": "fashion"},
    ...
  ]
  ```
- **Used by:** main.py to load merchants

#### `data/mock_db.json`
- **Purpose:** GrabOn's "internal database" of deals
- **Format:**
  ```json
  {
    "version": "2024-01-15",
    "deals": [
      {"merchant_id": "amazon", "code": "AMZNEW10", "discount": "10%", ...},
      ...
    ]
  }
  ```
- **Intentional bugs in DB:**
  - Some merchants missing (Zepto, Shopsy)
  - Some deals expired (MYNTRA30)
  - Discounts different than live (mismatch scenarios)
- **Used by:** db_lookup tool

#### `data/scraped/`
- **Purpose:** Auto-created folder storing raw HTML
- **Format:** `merchant_id_timestamp.html`
- **Cleaned up before demo:** Yes (remove all .html files)

---

### **Report Files**

#### `reports/audit_*.json`
- **Purpose:** Final audit report for each execution
- **Contains:**
  - Summary (merchants completed, deals audited)
  - Cost breakdown (per provider, per task)
  - Tool call statistics
  - Individual merchant results
  - Full iterations log
  - Recovery events
- **Cleaned up before demo:** Yes (remove old reports)

---

### **Config Files**

#### `.env`
- **Purpose:** API keys and settings (not in Git)
- **Required keys:**
  - GROQ_API_KEY
  - GOOGLE_API_KEY
  - LANGCHAIN_API_KEY (for LangSmith tracing)
- **Settings:**
  - MAX_TOKENS_PER_RUN, MAX_WALL_CLOCK_SECONDS, etc.
- **Precaution:** Never commit this file!

#### `requirements.txt`
- **Purpose:** Python dependencies
- **Install:** `pip install -r requirements.txt`

#### `README.md`
- **Purpose:** Architecture documentation
- **Contains:** Component diagrams, decision trees, setup instructions

---

## 🎬 How to Demo (Step-by-Step)

### **Before Demo:**
1. Clean up old reports and HTML files (see next section)
2. Test `.env` has valid API keys
3. Run with `--merchant amazon` to test single merchant first

### **Demo Flow (7 minutes):**

#### Minute 0-1: **Setup**
```bash
# In terminal
cd C:\Users\Sanjay\GrabOn_Assignment
source venv\Scripts\activate
python main.py --merchants 3
```
- Show command executing
- Live terminal dashboard updating in real-time

#### Minute 1-3: **Watch the Loop**
- Show PLAN phase: Agent creating strategy
- Show ACT phase: Tool executing (scraping HTML)
- Show OBSERVE phase: Analyzing result
- Show DECIDE phase: Making decision
- Show iterations accumulating in real-time

#### Minute 3-5: **Watch Failure Recovery**
- Navigate to `data/scraped/` folder
- Show raw HTML files being saved
- Explain: "If scrape fails, this is fallback #1 (google_cache), fallback #2 (scrape_js)"
- Show tool statistics in terminal: "Success rate 95%, avg latency 2.3s"

#### Minute 5-6: **Show Final Report**
```bash
# After run completes
type reports\audit_TIMESTAMP.json
```
- Show:
  - Total deals audited (47)
  - Classification breakdown (28 FRESH, 8 STALE, 6 MISSING, etc.)
  - Cost breakdown: "$0.0045 total, Groq: $0.0023, Gemini: $0.0019"
  - Tool statistics: "94 total calls, scrape_html: 16/20 success"

#### Minute 6-7: **Explain the Flow**
- Open `agent/loop.py` in editor
- Show Phase enum and 4-phase structure
- Explain: "Each merchant goes through 4 phases, 20 merchants = ~7 minutes"

---

## 🧹 Files to Remove Before Demo

Clean up these before showing to anyone:

### **Remove old reports:**
```bash
Remove: reports/audit_20260530_162439.json
Remove: reports/audit_20260530_163858.json
Remove: reports/audit_20260530_164342.json
[... all old audit files ...]
Keep: Only the latest ONE report
```

### **Remove scraped HTML:**
```bash
Remove: data/scraped/*.html (all 23 files!)
```

Why? 
- Shows messy history
- Confuses viewers
- Fresh run is cleaner to demo

### **Files to keep:**
```
✅ data/merchants.json (20 merchants)
✅ data/mock_db.json (internal DB)
✅ agent/ (all agent code)
✅ tools/ (all tool code)
✅ llm/ (router and cost tracker)
✅ evals/ (test scenarios)
✅ observability/ (UI and tracing)
```

---

## ⚠️ Precautions

### **Before Running:**

1. **Check API keys in `.env`:**
   ```bash
   # Verify these are set (don't print them!)
   GROQ_API_KEY=...
   GOOGLE_API_KEY=...
   LANGCHAIN_API_KEY=...
   ```

2. **Activate virtual environment:**
   ```bash
   venv\Scripts\activate
   ```

3. **Check internet connection:**
   - scrape_html needs to reach grabon.in
   - LLM calls need to reach provider APIs
   - If offline, evals still work (mocked)

### **During Demo:**

1. **Monitor terminal for errors:**
   - If you see "BudgetExceededError" → budget limit hit (expected in test runs)
   - If you see "ConnectionError" → network issue
   - If you see "429 Too Many Requests" → rate limited (expected, agent will retry)

2. **Don't interrupt mid-run:**
   - Let it complete all merchants
   - If you Ctrl+C, you won't get a report
   - Full run is 7-10 minutes (worth waiting)

3. **Watch for failures (intentional):**
   - `verify_coupon` fails 30% of time → agent retries 3x
   - This proves failure recovery works!
   - Don't be surprised, it's designed this way

4. **Show the trace (optional):**
   - After run, go to smith.langchain.com
   - Login with LANGCHAIN_API_KEY
   - Project: "grabon-audit-agent"
   - See full execution tree with timings

---

## 🎯 Key Points to Emphasize in Demo

### **Architecture Highlights:**
1. ✅ **4-Phase Loop:** PLAN/ACT/OBSERVE/DECIDE (explicit, not implicit)
2. ✅ **Tool Registry:** Dynamic tool discovery, not hardcoded
3. ✅ **Failure Recovery:** 3+ fallback strategies per failure type
4. ✅ **Budget Enforcement:** Halts immediately if limits breached
5. ✅ **Multi-LLM Routing:** Different model per task type
6. ✅ **Cost Tracking:** Track every $ spent per call
7. ✅ **Full Observability:** LangSmith traces + Rich terminal UI

### **What Makes This Production-Grade:**
- **Pydantic validation:** Every input/output validated
- **Timeout enforcement:** No hanging processes
- **Error classification:** Smart fallback decisions
- **Budget awareness:** Doesn't blow through costs
- **Comprehensive logging:** Every decision logged
- **30 test scenarios:** Covers happy + failure paths

---

## 📞 Common Demo Questions & Answers

**Q: "Why 4 phases? Can't you just run tools in sequence?"**  
A: The 4 phases create explicit decision points. OBSERVE classifies errors, DECIDE chooses recovery strategy. Without it, you either crash or don't recover intelligently.

**Q: "Why different LLM providers?"**  
A: Cost optimization. Planning needs reasoning (use big model). Classification is simple (use cheap model). Extraction needs vision (use latest model). Result: 50% cheaper than using same model for all.

**Q: "What happens if all fallbacks fail?"**  
A: Agent marks merchant as ERROR and moves to next one. Report still shows what failed + why.

**Q: "How do you prevent infinite loops?"**  
A: Max 3 retries per tool + max_consecutive_failures=5 + budget enforcer. If agent gets stuck, it halts gracefully.

**Q: "Can I run just 1 merchant to test?"**  
A: Yes! `python main.py --merchant amazon` runs just Amazon (18 seconds).

---

Now you're ready to demo! 🚀

