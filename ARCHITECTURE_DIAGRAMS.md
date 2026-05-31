# 🏗️ VISUAL ARCHITECTURE DIAGRAMS

## 1. OVERALL SYSTEM ARCHITECTURE

```
┌────────────────────────────────────────────────────────────────────────┐
│                         GrabOn Audit Agent                             │
│                                                                        │
│  main.py  ←─ Load 20 merchants from data/merchants.json               │
│   │                                                                    │
│   ▼                                                                    │
│ ┌──────────────────────────────────────────────────────────────────┐  │
│ │  AgentLoop (agent/loop.py) ⭐ MAIN ENGINE                       │  │
│ │                                                                  │  │
│ │  For each merchant: PLAN → ACT → OBSERVE → DECIDE               │  │
│ │                                                                  │  │
│ │  ┌─────────────────────────────────────────────────────────┐    │  │
│ │  │  PLAN Phase                                             │    │  │
│ │  │  ├─ AgentPlanner (LLM) thinks about strategy           │    │  │
│ │  │  ├─ Groq llama-3.1-70b model                           │    │  │
│ │  │  └─ Output: "Do steps 1,2,3,4"                         │    │  │
│ │  └─────────────────────────────────────────────────────────┘    │  │
│ │           ▼                                                       │  │
│ │  ┌─────────────────────────────────────────────────────────┐    │  │
│ │  │  ACT Phase                                              │    │  │
│ │  │  ├─ ToolRegistry.execute(tool_name, **params)         │    │  │
│ │  │  ├─ Timeout enforcement                                │    │  │
│ │  │  └─ Returns: ToolResult(success, data, error_type)    │    │  │
│ │  └─────────────────────────────────────────────────────────┘    │  │
│ │           ▼                                                       │  │
│ │  ┌─────────────────────────────────────────────────────────┐    │  │
│ │  │  OBSERVE Phase                                          │    │  │
│ │  │  ├─ Classify error:                                     │    │  │
│ │  │  │  ├─ SUCCESS                                          │    │  │
│ │  │  │  ├─ TRANSIENT (safe to retry)                       │    │  │
│ │  │  │  ├─ RATE_LIMIT (403/429)                           │    │  │
│ │  │  │  ├─ NOT_FOUND (404)                                │    │  │
│ │  │  │  └─ PERMANENT (bad)                                │    │  │
│ │  │  └─ Log to iterations_log                              │    │  │
│ │  └─────────────────────────────────────────────────────────┘    │  │
│ │           ▼                                                       │  │
│ │  ┌─────────────────────────────────────────────────────────┐    │  │
│ │  │  DECIDE Phase (Decision Tree)                           │    │  │
│ │  │                                                         │    │  │
│ │  │  if success and more_steps:                            │    │  │
│ │  │      → CONTINUE                                        │    │  │
│ │  │  elif error_type == TRANSIENT and retry_count < 3:    │    │  │
│ │  │      → RETRY (wait 2^retry_count seconds)             │    │  │
│ │  │  elif error_type == RATE_LIMIT:                       │    │  │
│ │  │      → WAIT 30s then RETRY                            │    │  │
│ │  │  elif error_type == NOT_FOUND:                        │    │  │
│ │  │      → SWITCH_TOOL (try google_cache)                 │    │  │
│ │  │  elif error_type == TIMEOUT:                          │    │  │
│ │  │      → SWITCH_TOOL (try scrape_js if was scrape_html) │    │  │
│ │  │  elif error_type == PERMANENT:                        │    │  │
│ │  │      → REPLAN (ask planner for new strategy)          │    │  │
│ │  │  else:                                                │    │  │
│ │  │      → MERCHANT_FAILED (move to next)                 │    │  │
│ │  │                                                         │    │  │
│ │  │  Then: budget_enforcer.check_limits()                 │    │  │
│ │  └─────────────────────────────────────────────────────────┘    │  │
│ │           ▼                                                       │  │
│ │  Loop back to PLAN (repeat for next step)                       │  │
│ │                                                                  │  │
│ └──────────────────────────────────────────────────────────────────┘  │
│   │                           │                        │              │
│   ▼                           ▼                        ▼              │
│ ┌─────────────────┐  ┌──────────────────┐  ┌──────────────────────┐ │
│ │ Tool Registry   │  │ Budget Enforcer  │  │ LangSmith Tracer     │ │
│ │ (tools/)        │  │ (budget.py)      │  │ (langsmith_tracer.py)│ │
│ │                 │  │                  │  │                      │ │
│ │ 7 Tools:        │  │ Limits:          │  │ Traces:              │ │
│ │ 1. scrape_html  │  │ • Tokens: 150K   │  │ • Full session       │ │
│ │ 2. google_cache │  │ • Time: 900s     │  │ • Per merchant       │ │
│ │ 3. scrape_js    │  │ • Calls: 200     │  │ • Per tool call      │ │
│ │ 4. extract_deals│  │ • Failures: 5    │  │ • Searchable         │ │
│ │ 5. db_lookup    │  │                  │  │                      │ │
│ │ 6. classify     │  │ Halts if breached│  │ Viewable at:         │ │
│ │ 7. verify       │  │                  │  │ smith.langchain.com  │ │
│ │                 │  │                  │  │                      │ │
│ └─────────────────┘  └──────────────────┘  └──────────────────────┘ │
│   │                           │                        │              │
│   ▼                           ▼                        ▼              │
│ ┌─────────────────┐  ┌──────────────────┐  ┌──────────────────────┐ │
│ │ LLM Router      │  │ Terminal UI      │  │ Final Report         │ │
│ │ (router.py)     │  │ (terminal_ui.py) │  │ (reports/)           │ │
│ │                 │  │                  │  │                      │ │
│ │ Routes to:      │  │ Shows:           │  │ JSON report:         │ │
│ │ • Groq 70B      │  │ • Live progress  │  │ • Merchants: 20      │ │
│ │ • Gemini Flash  │  │ • Phase: PAOD    │  │ • Completed: 18      │ │
│ │ • Groq 8B       │  │ • Tool calls     │  │ • Deals audited: 47  │ │
│ │ • OpenRouter    │  │ • Tokens used    │  │ • Fresh/Stale/etc.   │ │
│ │ • Nvidia        │  │ • Cost so far    │  │ • Cost breakdown     │ │
│ │                 │  │ • Status icons   │  │ • Iterations log     │ │
│ │ Cost tracking   │  │ • Recent events  │  │ • Recovery events    │ │
│ │ per provider    │  │                  │  │                      │ │
│ └─────────────────┘  └──────────────────┘  └──────────────────────┘ │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. TOOL EXECUTION FLOW

```
┌─────────────────────────────────────────────────────────┐
│  Tool: scrape_html                                      │
│  Input: {url, delay_before, merchant_id}               │
└─────────────────────────────────────────────────────────┘
         │
         ▼
    Wait 2 seconds (respectful)
         │
         ▼
    Make HTTP GET request
         │
         ├─ 200 OK ────────────────────────────────────┐
         │                                              │
         ├─ 403 Forbidden (rate limited)               ├─► error_type: RATE_LIMIT
         │                                              │
         ├─ 404 Not Found                              ├─► error_type: NOT_FOUND
         │                                              │
         ├─ 429 Too Many Requests                      ├─► error_type: RATE_LIMIT
         │                                              │
         ├─ Timeout (>10s)                             ├─► error_type: TIMEOUT
         │                                              │
         └─ Connection error ──────────────────────────┴─► error_type: TRANSIENT
         │
         ▼
    Save HTML to data/scraped/merchant_timestamp.html
         │
         ▼
    Return ToolResult
    ├─ html: "<!DOCTYPE html>..."
    ├─ status_code: 200
    ├─ saved_path: "data/scraped/amazon_20260531_123456.html"
    └─ error_type: null


┌─────────────────────────────────────────────────────────┐
│  Tool: extract_deals                                    │
│  Input: {html, merchant_name, merchant_id}             │
└─────────────────────────────────────────────────────────┘
         │
         ▼
    Truncate HTML to 8000 chars
         │
         ▼
    Call Gemini Flash LLM with extraction prompt
    "Parse this HTML and extract all coupon codes"
         │
         ▼
    LLM returns JSON:
    {
      "deals": [
        {"code": "AMZNEW10", "discount": "10%", "expiry": "2025-12-31"},
        {"code": "PRIMESAVE", "discount": "15%", "expiry": "2025-06-30"}
      ],
      "extraction_confidence": 0.95
    }
         │
         ▼
    Return ToolResult
    └─ data: {...json above...}


┌─────────────────────────────────────────────────────────┐
│  Tool: db_lookup                                        │
│  Input: {merchant_id}                                  │
└─────────────────────────────────────────────────────────┘
         │
         ▼
    Load data/mock_db.json
         │
         ▼
    Filter deals by merchant_id
         │
         ▼
    Return ToolResult
    └─ data: {
        "deals": [...],
        "merchant_found": true,
        "deal_count": 2
       }


┌─────────────────────────────────────────────────────────┐
│  Tool: classify_deals                                   │
│  Input: {merchant_id, db_deals, live_deals}            │
└─────────────────────────────────────────────────────────┘
         │
         ▼
    Compare each deal using business logic:
         │
         ├─ Code in DB AND on page AND same discount ──► FRESH ✅
         ├─ Code on page but discount changed ──────────► STALE ⚠️
         ├─ Code in DB but NOT on page ────────────────► MISSING ❌
         ├─ Code on page but NOT in DB ────────────────► EXTRA ✨
         └─ Code in DB AND on page but discount changed► UPDATED 🔄
         │
         ▼
    Calculate merchant_health_score = FRESH / Total
         │
         ▼
    Return ToolResult
    └─ data: {
        "classified_deals": [...],
        "summary": {"fresh": 5, "stale": 2, ...},
        "merchant_health_score": 0.833
       }
```

---

## 3. FAILURE RECOVERY DECISION TREE

```
┌────────────────────────────────────┐
│  Tool Execution Result             │
└────────────────────┬───────────────┘
                     │
         ┌───────────┴───────────┐
         │                       │
         ▼                       ▼
    SUCCESS?                ERROR?
         │                       │
         │                   ┌───┴─────────────────────┐
         │                   │                         │
         │                   ▼                         ▼
         │              Classify Error Type      Check Retry Count
         │                   │
         │         ┌─────────┼─────────┬─────────┬──────────┐
         │         │         │         │         │          │
         │         ▼         ▼         ▼         ▼          ▼
         │     TRANSIENT RATE_LIMIT NOT_FOUND TIMEOUT PERMANENT
         │         │         │         │         │          │
         │     retry<3?   wait     switch      switch    replan
         │     /    \      30s      to        to        or
         │    Y      N              cache     js_scraper fail
         │    │      │              │         │          │
         │    │   switch            │         │          │
         │    │   tool or           │         │          │
         │    │   replan            │         │          │
         │    │                     │         │          │
         │    └─────┬───────────────┘─────────┘          │
         │          │                                     │
         ▼          ▼                                     ▼
    CONTINUE   [Fallback Action]               Check if replan
       or          │                           or mark FAILED
    NEXT_STEP      ▼
                Try alternative tool
                   │
         ┌─────────┼─────────┐
         ▼         ▼         ▼
    Success   Still Error   Max Retries
       │         │          Exceeded
       │         │          │
       ▼         ▼          ▼
    Continue   If replan → Try again    Mark merchant
       next     Else → Mark FAILED      ERROR, move on
       step
```

---

## 4. DATA FLOW: One Merchant Lifecycle

```
START: Amazon merchant

Step 1: PLAN
  Input: Amazon details + available tools
  LLM: "Create a plan"
  Output: 
    [
      {"step": 1, "tool": "scrape_html", ...},
      {"step": 2, "tool": "extract_deals", ...},
      {"step": 3, "tool": "db_lookup", ...},
      {"step": 4, "tool": "classify_deals", ...}
    ]

Step 2a: ACT → scrape_html
  Input: https://www.grabon.in/amazon-coupons/
  Output: ToolResult(html="...", status_code=200, ...)
  
Step 2b: OBSERVE
  Result: SUCCESS (200 OK)
  Classification: COMPLETE
  
Step 2c: DECIDE
  Decision: CONTINUE (have HTML, move to next step)
  ✅ Budget OK, iterations += 1

Step 3a: ACT → extract_deals
  Input: html (45KB), merchant_name="Amazon"
  Call: Gemini Flash LLM
  Output: ToolResult(data={"deals": [...]}, ...)
  
Step 3b: OBSERVE
  Result: SUCCESS
  Classification: COMPLETE (got 3 coupons)
  
Step 3c: DECIDE
  Decision: CONTINUE (have deals, move to next step)
  ✅ Budget OK, iterations += 1

Step 4a: ACT → db_lookup
  Input: merchant_id="amazon"
  Output: ToolResult(data={"deals": [...], "deal_count": 2})
  
Step 4b: OBSERVE
  Result: SUCCESS
  Classification: COMPLETE
  
Step 4c: DECIDE
  Decision: CONTINUE (have DB deals, move to next step)
  ✅ Budget OK, iterations += 1

Step 5a: ACT → classify_deals
  Input: db_deals=[AMZNEW10, PRIMESAVE], live_deals=[AMZNEW10, PRIMESAVE]
  Output: ToolResult(data={
    "classified_deals": [
      {"code": "AMZNEW10", "classification": "FRESH"},
      {"code": "PRIMESAVE", "classification": "FRESH"}
    ],
    "summary": {"fresh": 2, "stale": 0, ...}
  })
  
Step 5b: OBSERVE
  Result: SUCCESS
  Classification: COMPLETE
  
Step 5c: DECIDE
  Decision: MERCHANT_COMPLETE (no more steps)
  ✅ Budget OK, iterations += 1

Store MerchantResult:
  {
    "merchant_id": "amazon",
    "name": "Amazon",
    "status": "completed",
    "health_score": 1.0,
    "tool_calls": 5,
    "time_taken": 23.4
  }

END: Move to next merchant (Myntra)
```

---

## 5. BUDGET ENFORCEMENT TIMELINE

```
Time ──────────────────────────────────────────────────► 900s (limit)
      │       │       │       │       │       │       │
      0       100     200     300     400     500     600

Merchant 1 (90s)    Merchant 2 (85s)    Merchant 3 (92s)
├─ Tokens: 1500     ├─ Tokens: 1600     ├─ Tokens: 1700
└─ Calls: 5         └─ Calls: 5         └─ Calls: 5

Total so far at 300s: 4800 tokens / 150K (3%), 15 calls / 200 (8%)

      │       │       │       │       │       │       │
      0       150     300     450     600     750     900

... continuing ...

At 870s:
├─ Total tokens: 52,000 / 150,000 ✅ (35% used)
├─ Total calls: 87 / 200 ✅ (44% used)
├─ Wall clock: 870s / 900s ⚠️ (96% used)
└─ Consecutive failures: 0 / 5 ✅

At 898s (Merchant 19, step 3):
├─ New tokens required: 1200 (would need 53,200 total)
├─ Budget check: ✅ OK
├─ Execute tool call

At 915s: ❌ HALT
├─ Wall clock > 900s
├─ Stop accepting new merchants
├─ Generate PARTIAL report (19/20 completed)
└─ Exit code: 2 (budget exceeded)
```

---

## 6. COST STRUCTURE

```
Per LLM Provider Call:
┌────────────────────────────────────────────┐
│ Groq (llama-3.1-70b)                      │
│ Planning task: 200 input + 150 output     │
│ Cost: (200 × $0.05 + 150 × $0.08) / 1000  │
│      = (10 + 12) / 1000 = $0.000022        │
└────────────────────────────────────────────┘

┌────────────────────────────────────────────┐
│ Gemini Flash (gemini-1.5-flash)           │
│ Extraction task: 1000 input + 200 output  │
│ Cost: (1000 × $0.075 + 200 × $0.30) / 1000│
│      = (75 + 60) / 1000 = $0.000135        │
└────────────────────────────────────────────┘

Per 20 Merchants (full run):
┌────────────────────────────────────────────┐
│ Planning: 20 × $0.000022 = $0.00044        │
│ Extraction: 20 × $0.000135 = $0.0027       │
│ Classification: 0 (no LLM) = $0            │
│ ─────────────────────────────────────────  │
│ TOTAL: ~$0.0031 ✅ (Less than 1 cent!)    │
└────────────────────────────────────────────┘

Why so cheap?
├─ Most tasks (classify, db_lookup) → no LLM call
├─ Cheap models for simple tasks (Groq 8B)
├─ Large models only for complex tasks (Gemini)
└─ Fallback chain: if provider A fails → use cheaper provider B
```

---

## 7. PHASE STATE DIAGRAM

```
START
  │
  ▼
┌─────────────────────────────┐
│ Load merchants              │
└──────────┬──────────────────┘
           │
           ▼
      FOR EACH MERCHANT
           │
           ▼
    ┌──────────────┐
    │ PLAN Phase   │
    │ (LLM thinks) │
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐
    │ ACT Phase    │
    │ (Run tool)   │────────────┐
    └──────┬───────┘            │
           │                    │
           ▼                    │
    ┌──────────────┐            │
    │ OBSERVE      │            │
    │ (Analyze)    │            │
    └──────┬───────┘            │
           │                    │
           ▼                    │
    ┌──────────────────────────────┐
    │ DECIDE Phase                 │
    │ ├─ Continue?  ─────► Back to ACT
    │ ├─ Retry? ────► Wait then ACT
    │ ├─ Switch? ───► New tool, ACT
    │ ├─ Replan? ───► Back to PLAN
    │ └─ Done? ─────► Next merchant
    └──────┬───────────────────────┘
           │
           ▼
    All merchants done?
           │
      ┌────┴────┐
      NO        YES
      │         │
      ▼         ▼
   Continue   Generate
               Report
               │
               ▼
              DONE
```

---

## 8. ERROR CLASSIFICATION → ACTION MAPPING

```
Error Type              Cause                          Action
═════════════════════════════════════════════════════════════════════
SUCCESS                 No error                       CONTINUE

TRANSIENT               • Timeout
                        • Connection reset
                        • 500 Server error              RETRY (max 3 times)
                                                       Then SWITCH_TOOL

RATE_LIMIT              • HTTP 429
                        • HTTP 403                     WAIT 30s then RETRY

NOT_FOUND               • HTTP 404
                        • Page doesn't exist           SWITCH_TOOL
                                                       (try google_cache)

TIMEOUT                 • Request >timeout_seconds     SWITCH_TOOL
                        • No response                  (try slower tool)

PERMANENT               • Invalid URL
                        • Auth required
                        • DNS error                    REPLAN or FAIL
```

---

