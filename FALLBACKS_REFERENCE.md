# GrabOn Merchant Deal Audit Agent — Fallback Mechanisms Reference

**Date:** June 1, 2026  
**Project:** GrabOn Merchant Deal Audit Agent  
**Purpose:** Complete catalog of all fallback strategies and where they're used

---

## 1. LLM Provider Fallbacks 🔄

### Location: [llm/router.py](llm/router.py)

#### 1.1 Deal Extraction Fallback Chain
**File:** [llm/router.py](llm/router.py#L237-L258)  
**Function:** `_fallback_extraction()`  
**When Used:** When primary LLM fails during deal extraction task

**Fallback Chain:**
```
Groq (small) 
  ↓ (if fails)
Gemini Flash 
  ↓ (if fails)
RAISE: ValueError("No extraction fallback provider available")
```

**Error Handling:**
- Catches exceptions from each provider
- Logs warning: `"Fallback extraction failed with {provider_name}"`
- Returns tuple: `(response_text, input_tokens, cost_usd, provider_name)`

**Usage Points:**
- Called from [llm/router.py#L223](llm/router.py#L223) in `call_with_tracking()` method
- Triggered when `task == TaskType.DEAL_EXTRACTION` and primary fails

---

#### 1.2 Planning Fallback Chain
**File:** [llm/router.py](llm/router.py#L275-L318)  
**Function:** `_fallback_planning()`  
**When Used:** When primary LLM fails during plan generation task

**Fallback Chain:**
```
Gemini Flash
  ↓ (if fails)
OpenRouter
  ↓ (if fails)
Groq (small)
  ↓ (if fails)
RAISE: ValueError("No planning fallback provider available")
```

**Error Handling:**
- Logs info: `"Fallback planning succeeded with {provider_name}"`
- Logs warning: `"Fallback planning failed: {e}"`
- Returns tuple: `(response_text, input_tokens, cost_usd, provider_name)`

**Usage Points:**
- Called from [llm/router.py#L223](llm/router.py#L223) in `call_with_tracking()` method
- Triggered when `task == TaskType.PLANNING` and primary fails

---

### Trigger in call_with_tracking()
**File:** [llm/router.py](llm/router.py#L197-L230)  
**Method:** `call_with_tracking()`

```python
# If primary provider fails, attempt fallback
if task == TaskType.DEAL_EXTRACTION:
    return self._fallback_extraction(prompt, max_tokens)
elif task == TaskType.PLANNING:
    return self._fallback_planning(prompt, max_tokens)
else:
    raise
```

---

## 2. Tool-Level Fallbacks 🛠️

### Location: [agent/loop.py](agent/loop.py) — DECIDE Phase

**File:** [agent/loop.py](agent/loop.py#L539-L680)  
**Function:** `_phase_decide()`  
**Purpose:** Determine recovery action based on tool failure type

### 2.1 Rate Limit Recovery (HTTP 403)

**Error Type:** `RATE_LIMIT`  
**Primary Tool:** `scrape_html`

**Fallback Chain:**
```
HTTP Scraper (scrape_html)
  ↓ (403 Forbidden)
Google Cache Fallback
  ↓ (if fails)
JavaScript Scraper (scrape_js)
  ↓ (if fails)
Static Template (graceful degradation)
```

**Location:** [agent/loop.py](agent/loop.py#L600-L615)

**Code:**
```python
elif tool_result.error_type == "RATE_LIMIT":
    if tool_name == "scrape_html":
        decision = "SWITCH_TOOL:google_cache"  # Try cache first
        reasoning = "HTTP scrape blocked, switching to cache"
    elif tool_name == "google_cache":
        decision = "SWITCH_TOOL:scrape_js"     # Then JS scraper
        reasoning = "Cache unavailable, switching to JS scraper"
    elif tool_name == "scrape_js":
        decision = "SWITCH_TOOL:static_template"  # Final fallback
        reasoning = "JS scrape blocked, using static template"
    elif tool_name == "static_template":
        decision = "MERCHANT_FAILED"            # All exhausted
        reasoning = "All scrapers blocked, merchant failed"
```

**Test Scenarios:**
- TC011: Myntra - 403 → cache → success (STALE deal)
- TC012: Zomato - Timeout → JS scraper → success (FRESH)
- TC013: MakeMyTrip - All fail → graceful UNKNOWN

---

### 2.2 Timeout Recovery

**Error Type:** `TIMEOUT`  
**Primary Tool:** `scrape_html`

**Fallback Chain:**
```
HTTP Scraper (scrape_html)
  ↓ (30s timeout)
JavaScript Scraper (scrape_js) [more reliable but slower]
  ↓ (if times out)
Static Template (mock data)
```

**Location:** [agent/loop.py](agent/loop.py#L628-L638)

**Code:**
```python
elif tool_result.error_type == "TIMEOUT":
    if tool_name == "scrape_html":
        decision = "SWITCH_TOOL:scrape_js"
        reasoning = "HTTP scrape timed out, switching to JS-capable scraper"
    elif tool_name == "scrape_js":
        decision = "SWITCH_TOOL:static_template"
        reasoning = "Page not found via JS, using static template fallback"
```

---

### 2.3 Not Found (404) Recovery

**Error Type:** `NOT_FOUND`  
**Primary Tool:** Any scraper

**Fallback Chain:**
```
HTTP Scraper (scrape_html)
  ↓ (404)
JavaScript Scraper (scrape_js)
  ↓ (404)
Static Template (fallback data)
  ↓ (if unavailable)
MERCHANT_FAILED
```

**Location:** [agent/loop.py](agent/loop.py#L616-L627)

**Code:**
```python
elif tool_result.error_type == "NOT_FOUND":
    if tool_name == "scrape_html":
        decision = "SWITCH_TOOL:scrape_js"
        reasoning = "Page not found, trying JS-capable scraper"
    elif tool_name == "scrape_js":
        decision = "SWITCH_TOOL:static_template"
        reasoning = "Page not found via JS, using static template fallback"
    elif tool_name == "static_template":
        decision = "MERCHANT_FAILED"
        reasoning = "Static template unavailable, merchant failed"
```

**Test Scenario:** TC023: BigBasket - 404 on all tools → MERCHANT_FAILED

---

### 2.4 Transient Error Recovery (Network/Timeout)

**Error Type:** `TRANSIENT`  
**Recovery:** Retry with exponential backoff

**Location:** [agent/loop.py](agent/loop.py#L584-L615)

**Retry Strategy:**
```python
if tool_name == "scrape_html":
    decision = "SWITCH_TOOL:scrape_js"          # Try alternative tool
elif retry_count < 3:
    decision = "RETRY"                           # Exponential backoff
    wait_time = 2 ** min(retry_count, 3)        # 2s, 4s, 8s (capped)
elif retry_count >= 3:
    decision = "REPLAN"                          # Give up, replan
```

**Backoff Formula:**
- Attempt 1: Wait 2¹ = 2 seconds
- Attempt 2: Wait 2² = 4 seconds
- Attempt 3: Wait 2³ = 8 seconds (capped)
- Attempt 4+: Trigger REPLAN

**Test Scenarios:**
- TC014: Amazon verify fails 2x → succeeds on 3rd (FRESH)
- TC015: Flipkart JSON parse error → retry → success (EXTRA)

---

### 2.5 Permanent Error Recovery

**Error Type:** `PERMANENT`  
**Recovery:** Full replan with alternative tools

**Location:** [agent/loop.py](agent/loop.py#L657-L672)

**Code:**
```python
elif tool_result.error_type == "PERMANENT":
    if tool_name == "scrape_html":
        decision = "REPLAN"
        reasoning = "Permanent scraping failure, replanning with JS fallback"
    elif tool_name == "scrape_js":
        decision = "REPLAN"
        reasoning = "Permanent JS failure, replanning with alternatives"
```

---

## 3. Replanning (Dynamic Fallback) 📋

### Location: [agent/planner.py](agent/planner.py)

**File:** [agent/planner.py](agent/planner.py#L156-L245)  
**Function:** `replan()`  
**When Used:** When tool fails permanently or max retries exceeded

**Replanning Triggers:**
```
Tool Failure (error_type = PERMANENT)
  ↓
AgentLoop calls planner.replan()
  ↓
Planner creates alternative plan with fallback tools
  ↓
Agent executes new plan
```

**Error Recovery Strategy:** [agent/planner.py](agent/planner.py#L308-L327)

```python
def _get_error_strategy(self, error_type: str) -> str:
    strategies = {
        "TRANSIENT": "Retry with exponential backoff or use alternative tool",
        "RATE_LIMIT": "Try scrape_js, then static_template if blocked",
        "NOT_FOUND": "Mark merchant as unavailable",
        "TIMEOUT": "Switch to slower tool (e.g., Playwright)",
        "PERMANENT": "Use static_template fallback or graceful degradation",
    }
    return strategies.get(error_type, "Use fallback tool")
```

**Replan Prompt Includes:**
```json
{
  "steps": [
    {"step": 1, "tool": "static_template", "reason": "Fallback: generate from mock DB"},
    {"step": 2, "tool": "extract_deals", "reason": "Extract from fallback"},
    {"step": 3, "tool": "db_lookup", "reason": "Get DB records"},
    {"step": 4, "tool": "classify_deals", "reason": "Classify deals"}
  ],
  "fallback_if_scrape_fails": "static_template",
  "estimated_tool_calls": 4
}
```

**Location in Planner:** [agent/planner.py](agent/planner.py#L200-L245)

---

## 4. Empty Response Handling 🔲

### Location: [agent/loop.py](agent/loop.py)

**Scenario:** Scraper succeeds but returns empty HTML

**Location:** [agent/loop.py](agent/loop.py#L584-L598)

**Fallback Chain:**
```
scrape_html returns empty string
  ↓
Detect: tool_result.html == ""
  ↓
SWITCH_TOOL:scrape_js
  ↓ (try JavaScript-capable scraper)
```

**Code:**
```python
if tool_name == "scrape_html" and tool_result.html == "":
    decision = "SWITCH_TOOL:scrape_js"
    reasoning = "Empty HTML response, trying JS-capable scraper"
```

**Test Scenario:** TC018: Swiggy - Empty HTML → scrape_js fallback succeeds (FRESH)

---

## 5. Database Fallback 📊

### Location: [agent/loop.py](agent/loop.py) & [tools/db_lookup.py](tools/db_lookup.py)

**Scenario:** DB has no deals, but live deals found

**Behavior:**
```
db_lookup.get_deals(merchant_id)
  ↓ (returns empty list)
Agent classifies live scraped deals as "EXTRA" (new deals)
  ↓
Marked as EXTRA in final classification
```

**Expected Decision:** `CONTINUE` (not error)  
**Expected Outcome:** `completed`  
**Classification:** All deals marked as `EXTRA`

**Test Scenario:** TC017: Meesho - Empty DB → all live deals = EXTRA

---

## 6. Multi-LLM Fallback 🤖

### Location: [evals/scenarios.py](evals/scenarios.py) — Multi-LLM Category

**Scenario:** Primary LLM fails during extraction

**Test Scenarios:**

#### TC028: Provider Fallback Chain
- Gemini Flash times out during EXTRACTION
- Router automatically uses Groq fallback
- Result: FRESH deal (if within expiry)

**Mock Response:**
```python
"provider_sequence": ["gemini", "groq"],
"gemini": {"success": False, "error": "Timeout"},
"groq": {"success": True, "deals": [...]}
```

#### TC029: Cost Tracking with Fallback
- Primary provider costs tracked
- Fallback provider substituted with cost recorded
- Agent continues with alternate provider

#### TC030: Cheap Model Selection
- Router selects cheaper provider when cost exceeds threshold
- Falls back from expensive (Gemini) to cheaper (Groq)
- Budget constraint respected

---

## 7. Verification Tool Fallback ✓

### Location: [tools/unreliable_verifier.py](tools/unreliable_verifier.py)

**Scenario:** Coupon verification fails transiently

**Fallback Behavior:**
```
verify_coupon(code)
  ↓ (Attempt 1: FAIL - ConnectionError)
  ↓ (Attempt 2: FAIL - TimeoutError)
  ↓ (Attempt 3: SUCCESS - is_active=True)
Decision: RETRY with backoff
Final: FRESH (verified valid)
```

**Test Scenario:** TC014: Amazon - Verifier retries 2x then succeeds

---

## 8. Static Template Fallback 🎯

### Location: [tools/static_template.py](tools/static_template.py)

**Purpose:** Generate mock HTML when all other tools fail

**When Used:**
- After HTTP scraper fails (403)
- After JS scraper fails (timeout/blocked)
- After cache lookup fails (rate limited)
- Last resort before MERCHANT_FAILED

**Template Data:**
- Mock HTML structure with standard deal divs
- Fake merchant logo and layout
- Pre-populated test deals

**Returns:** Simulated HTML as if scraped from merchant

---

## 9. Google Cache Fallback 📇

### Location: [tools/scraper_html.py](tools/scraper_html.py) — cache lookup

**When Used:** When main HTTP scraper returns 403 Forbidden

**Query Format:** `https://webcache.googleusercontent.com/cache:{merchant_url}`

**Fallback Chain:**
```
HTTP Request to merchant_url
  ↓ (403 Forbidden)
Try Google Cache (cached version)
  ↓ (if available)
Extract deals from cached HTML
  ↓ (if cache fails)
Switch to scrape_js
```

**Limitation:** Cached version may be stale (old deals)

**Test Scenario:** TC011: Myntra - 403 → cache → STALE deal classification

---

## 10. Failure Cascade Summary 🔀

```
Level 1: TRANSIENT Error
├─ Retry with 2^n backoff (2s, 4s, 8s)
└─ After 3 attempts → Level 2

Level 2: RATE_LIMIT / NOT_FOUND / TIMEOUT
├─ Switch tool (scrape_html → google_cache → scrape_js → static_template)
└─ If all tools fail → Level 3

Level 3: PERMANENT Error
├─ Request full REPLAN with alternative strategies
└─ If replan fails → Level 4

Level 4: ALL_EXHAUSTED
└─ MERCHANT_FAILED (graceful degradation, mark as ERROR)
```

---

## 11. Validation & Testing 🧪

### Location: [evals/runner.py](evals/runner.py)

**Validation Function:** `_test_failure_recovery()` [evals/runner.py](evals/runner.py#L239-L360)

**Checks:**
1. Primary tool fails with expected error_type ✓
2. Agent makes recovery decision (RETRY / SWITCH_TOOL / REPLAN) ✓
3. Fallback tool attempts or retry succeeds ✓
4. Final status reflects recovery (completed or error) ✓

**Recovery Decisions Validated:**
```
RETRY              → Exponential backoff triggered
SWITCH_TOOL:X      → Alternative tool available
MERCHANT_FAILED    → All fallbacks exhausted
REPLAN             → Alternative plan created
```

**Fallback Coverage in Tests:**

| Fallback Type | Test Case | Trigger | Recovery | Outcome |
|---|---|---|---|---|
| HTTP 403 | TC011 | scrape_html blocked | google_cache | STALE |
| Timeout | TC012 | HTTP timeout | scrape_js | FRESH |
| All fail | TC013 | All scrapers fail | none | ERROR |
| Retry | TC014 | verify fails 2x | retry backoff | FRESH |
| JSON parse | TC015 | malformed response | extractor retry | EXTRA |
| Empty DB | TC017 | no DB deals | classify as EXTRA | COMPLETED |
| Empty HTML | TC018 | empty response | scrape_js | FRESH |
| Not found | TC023 | 404 status | static_template | ERROR |
| LLM timeout | TC028 | Gemini fails | Groq fallback | FRESH |

---

## Summary Table: All Fallbacks at a Glance

| Fallback Type | Layer | Trigger | Fallback Action | Location | Recovery? |
|---|---|---|---|---|---|
| **LLM Extraction** | LLM | Provider timeout/error | Groq → Gemini | `llm/router.py:237` | ✓ Yes |
| **LLM Planning** | LLM | Provider error | Gemini → OpenRouter → Groq | `llm/router.py:275` | ✓ Yes |
| **HTTP 403** | Tool | Rate limit | google_cache → scrape_js | `agent/loop.py:600` | ✓ Yes |
| **Timeout** | Tool | Network delay | scrape_js → static_template | `agent/loop.py:628` | ✓ Yes |
| **404 Not Found** | Tool | Page missing | scrape_js → static_template | `agent/loop.py:616` | ✓ Yes |
| **Transient** | Retry | Network hiccup | Retry with 2^n backoff | `agent/loop.py:584` | ✓ Yes |
| **Permanent** | Replan | Tool failure | Full replan with alternatives | `agent/planner.py:156` | ✓ Yes |
| **Empty HTML** | Tool | No data returned | scrape_js fallback | `agent/loop.py:584` | ✓ Yes |
| **Verify Fail** | Retry | Transient verify error | Retry with backoff | `tools/unreliable_verifier.py` | ✓ Yes |
| **Empty DB** | Handle | No DB records | Classify live deals as EXTRA | `agent/loop.py` | ✓ Yes |
| **All Exhausted** | Final | All tools fail | MERCHANT_FAILED (graceful) | `agent/loop.py:680` | ✗ No |

---

## Code Metrics

**Total Fallback Mechanisms:** 10  
**LLM Provider Chains:** 2 (Extraction + Planning)  
**Tool Fallback Chains:** 4 (Rate Limit, Timeout, Not Found, Empty)  
**Retry Strategies:** 2 (Exponential backoff + Transient)  
**Graceful Degradations:** 2 (Static template, Unknown status)  

**Files Involved:**
- `llm/router.py` — LLM fallbacks (2)
- `agent/loop.py` — Tool & retry fallbacks (4)
- `agent/planner.py` — Replan fallback (1)
- `tools/unreliable_verifier.py` — Verify fallback (1)
- `tools/static_template.py` — Template fallback (1)
- `evals/runner.py` — Fallback validation (1)
- `evals/scenarios.py` — Fallback test scenarios (8 covered)

---

**End of Reference Document**
