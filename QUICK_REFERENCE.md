# 🚀 QUICK DEMO CHECKLIST & REFERENCE

## ⚡ 60-Second Explanation (If Interrupted)

```
This is a PAOD agent that audits GrabOn deals.

PLAN: LLM creates a 4-step strategy
ACT: Execute each tool (scrape, extract, compare)
OBSERVE: Analyze results (did it succeed or fail?)
DECIDE: Smart recovery (retry, switch tool, replan, or stop)

7 tools, 20 merchants, 7-10 minutes total.
Budget enforced → stops if costs explode or time limit hit.
```

---

## 📋 PRE-DEMO CHECKLIST

- [ ] Backup current reports folder: `reports/` → `reports_backup/`
- [ ] Clean `reports/` (remove all old .json files)
- [ ] Clean `data/scraped/` (remove all .html files)
- [ ] Check `.env` has API keys (don't print them!)
- [ ] Activate venv: `venv\Scripts\activate`
- [ ] Have README.md and DEMO_GUIDE.md open for reference
- [ ] Test with 1 merchant first: `python main.py --merchant amazon`
- [ ] Verify terminal dashboard appears

---

## ⏱️ DEMO SCRIPT (7 minutes)

### Min 0-1: SETUP
```bash
# Show starting point
pwd
# C:\Users\Sanjay\GrabOn_Assignment

# Show env is loaded
type .env | Select-String GROQ_API_KEY
# (Don't show actual key, just prove it's set)

# Start demo
python main.py --merchants 3
```
**What to say:** "Running audit for first 3 merchants (Amazon, Myntra, Zomato)"

### Min 1-3: WATCH THE LOOP
```
Terminal shows:
🤖 GrabOn Deal Audit Agent — LIVE
├─ CURRENT MERCHANT: Amazon [1/3]
├─ Phase: PLAN → ACT → OBSERVE → DECIDE
├─ Step 1 (PLAN): Created 4-step strategy
├─ Step 2 (ACT): Calling scrape_html...
├─ Step 3 (OBSERVE): Got 200 OK, 45KB HTML
├─ Step 4 (DECIDE): Continue to extract_deals
...
```
**What to say:** "Notice the 4 phases. Each merchant cycles through these. If scrape fails (403), it automatically tries google_cache."

### Min 3-4: OPEN FOLDERS
```bash
# Show saved HTML
ls data/scraped/ | head
# Shows: amazon_20260531_123456.html, myntra_20260531_123457.html, ...

# Show stats
# In terminal UI, scroll to show:
# "Tool calls: 12/200"
# "Tokens: 18,437/150,000"  
# "Cost: $0.0012"
```
**What to say:** "Raw HTML saved here. Budget enforcer tracking tokens and costs in real-time."

### Min 4-6: FINAL REPORT
```bash
# After run completes (or interrupt with Ctrl+C)
type reports\audit_TIMESTAMP.json | more
```
**What to show:**
```json
{
  "total_merchants": 3,
  "completed": 3,
  "summary": {
    "total_deals_audited": 9,
    "fresh": 6,
    "stale": 2,
    "missing": 1
  },
  "cost_breakdown": {
    "total_usd": 0.0023,
    "by_provider": {
      "groq": {"tokens": 5000, "cost_usd": 0.0008},
      "gemini": {"tokens": 8000, "cost_usd": 0.0015}
    }
  }
}
```
**What to say:** "Report shows: 9 deals audited, 6 are current, 2 expired, 1 missing from database. Total cost: $0.0023. Each provider tracked separately."

### Min 6-7: CODE WALKTHROUGH
```python
# Open agent/loop.py

# Show Phase enum
class Phase(str, Enum):
    PLAN = "PLAN"
    ACT = "ACT"
    OBSERVE = "OBSERVE"
    DECIDE = "DECIDE"

# Show main loop structure
async def run(self, merchants):
    for merchant in merchants:
        # PHASE 1: PLAN
        plan = await self.planner.create_plan(merchant)
        
        # PHASE 2: ACT
        result = await self.registry.execute(plan.steps[0].tool, **params)
        
        # PHASE 3: OBSERVE
        error_type = self._classify_error(result)
        
        # PHASE 4: DECIDE
        decision = self._decide_next_action(error_type, result)
        
        # Budget check
        self.budget_enforcer.check_limits()
```
**What to say:** "Pure 4-phase structure. No magic. Each phase has explicit logic. Budget enforcer stops entire agent if limits breached."

---

## 🔧 TOOLS (Quick Reference)

| Tool | Purpose | Speed | Cost | When Used |
|---|---|---|---|---|
| scrape_html | Download page | 2-5s | $0 | Primary |
| google_cache | Cache fallback | 3-8s | $0 | If 403 |
| scrape_js | JS rendering | 20-30s | $0 | Last resort |
| extract_deals | Parse coupons | 3s | $0.0001 | After scrape |
| db_lookup | Query DB | 0.1s | $0 | Get baseline |
| classify_deals | Compare | 0.5s | $0 | Final step |
| verify_coupon | Verify active | 1s | $0 | Optional (fails 30%) |

---

## ⚠️ WHAT TO EXPECT (Intentional Behavior)

✅ Terminal updates every iteration (flickers a bit - normal)  
✅ Delays between requests (2s pause = respectful scraping)  
✅ "429 Too Many Requests" (agent waits 30s then retries)  
✅ verify_coupon sometimes fails (30% intentional - shows recovery)  
✅ Report shows cost breakdown (proof of cost tracking)  
✅ LangSmith traces available (if LANGCHAIN_API_KEY set)  

---

## 🛑 PROBLEMS & SOLUTIONS

| Problem | Solution |
|---|---|
| "API key invalid" | Check .env has real key (not placeholder) |
| "Connection timeout" | Check internet connection |
| "Too many iterations logged" | Normal - agent logs every phase change |
| "Cost seems high" | Normal if using GPT-4. Try Groq (cheaper) |
| "Report file empty" | Interrupt Ctrl+C too early. Let run complete. |
| "Budget exceeded" | Normal - tests budget halting. Try `--merchants 1` |

---

## 💡 TALKING POINTS

### Strengths to Highlight:
1. **Explicit 4-phase loop** — every decision logged, no implicit behavior
2. **Intelligent fallbacks** — rate limit → cache, cache fails → browser automation
3. **Budget awareness** — stops before $ or time limits
4. **Multi-LLM routing** — cheap model for simple tasks, smart model for complex
5. **Full tracing** — every tool call traceable in LangSmith
6. **Recovers gracefully** — doesn't crash, logs what went wrong

### Technical Depth:
- Tool registry: Dynamic discovery via decorators
- Pydantic validation: Strict input/output schemas
- Error classification: 5 types (TRANSIENT/RATE_LIMIT/NOT_FOUND/PERMANENT/SUCCESS)
- Decision tree: 6 possible outcomes per error type
- Budget enforcement: 4 hard limits checked every iteration

### Why This Matters:
- **Production-grade:** Won't explode AWS bill, won't hang forever
- **Debuggable:** Every decision in trace, can replay with mocks
- **Extendable:** Add new tool = add 1 @register decorator
- **Cost-conscious:** Routes cheap model for 80% of work, expensive model for 20%

---

## 🎯 AFTER DEMO

1. **Save report** to `reports_backup/` for portfolio
2. **Take screenshot** of terminal dashboard
3. **Export LangSmith trace** (click share in smith.langchain.com)
4. **Clean up:**
   - Remove `data/scraped/*.html`
   - Keep latest `reports/audit_*.json` (only 1)

---

## 📱 PHONE A FRIEND (For Questions You Don't Know)

**Q: "What if a merchant has no deals?"**  
A: Agent marks it as CLEAN (not an error). Reported as 0 deals = healthy.

**Q: "How many tokens per merchant?"**  
A: ~1,500-2,000 tokens average. 20 merchants × 1,750 = 35,000 tokens = ~$0.015

**Q: "Why not just use one LLM?"**  
A: Cost. Using same LLM for all tasks = 3x more expensive. Better: cheap model for 80%, expensive for 20%.

**Q: "How long to audit all 20 merchants?"**  
A: 7-10 minutes depending on network. Each merchant ~30-40 seconds on average.

**Q: "What's the largest failure the agent recovered from?"**  
A: Rate limit (403) on first scrape → fallback to cache → succeeded. Fully transparent in trace.

---

## 🎬 DEMO VIDEO TIPS

If recording:
1. Start with `python main.py --merchants 3` (faster for video)
2. Speed up video 2x during slow scraping
3. Show final report at end (result matters)
4. Include LangSmith trace screen (adds wow factor)
5. Add voiceover explaining PAOD phases
6. Duration: 3-5 minutes edited down

---

