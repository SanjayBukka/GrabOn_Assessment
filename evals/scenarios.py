"""
Test scenarios for GrabOn audit agent evaluation suite.

Defines 30 test cases covering:
- Happy path scenarios (happy deals, new deals, edge cases)
- Failure and recovery (network, timeouts, fallbacks)
- Budget enforcement (token limits, time limits, tool call limits)
- Impossible cases (404 pages, blocked merchants, hallucination detection)
- Multi-LLM routing (provider fallbacks and cost tracking)

Each scenario is a dict with:
- id: Unique test case ID
- name: Descriptive test name
- category: One of [happy_path, failure_recovery, budget_exceeded, edge_cases, multi_llm]
- merchant_id: Merchant to test
- description: What this tests
- mock_responses: Dict with 'scraper', 'db', 'extractor' responses (or None for real)
- expected_decision: Expected agent decision
- expected_outcome: Expected final status
- should_retry: Whether agent should retry on failure
"""

from typing import Dict, List, Any, Optional


SCENARIOS: List[Dict[str, Any]] = [
    # ==================== HAPPY PATH (10 scenarios) ====================
    {
        "id": "TC001",
        "name": "Amazon - Exact match fresh deal",
        "category": "happy_path",
        "merchant_id": "amazon",
        "description": "Scraper finds deal with exact DB match and non-expired code",
        "mock_responses": {
            "scraper": {
                "success": True,
                "html": '<div class="coupon">AMZNEW10 - 10% off</div><span class="expiry">2025-12-31</span>',
                "status_code": 200,
            },
            "db": {
                "deals": [
                    {
                        "code": "AMZNEW10",
                        "discount": "10%",
                        "description": "10% off on electronics",
                        "expiry": "2025-12-31",
                        "min_order": 500,
                    }
                ]
            },
            "extractor": {
                "success": True,
                "deals": [
                    {
                        "code": "AMZNEW10",
                        "discount": "10%",
                        "description": "10% off on electronics",
                        "expiry": "2025-12-31",
                        "min_order": 500,
                    }
                ],
                "confidence": 0.95,
            },
        },
        "expected_decision": "CONTINUE",
        "expected_classification": "FRESH",
        "expected_outcome": "completed",
        "should_retry": False,
    },
    {
        "id": "TC002",
        "name": "Flipkart - Extra deal on live page",
        "category": "happy_path",
        "merchant_id": "flipkart",
        "description": "Live page has deal not in DB (new deal GrabOn needs to add)",
        "mock_responses": {
            "scraper": {
                "success": True,
                "html": '<div class="coupon">FLIPNEW - 25% off</div><div class="coupon">FLIPEXTRA - 30% off</div>',
                "status_code": 200,
            },
            "db": {
                "deals": [
                    {
                        "code": "FLIPNEW",
                        "discount": "25%",
                        "description": "25% off for new users",
                        "expiry": "2025-12-31",
                        "min_order": 0,
                    }
                ]
            },
            "extractor": {
                "success": True,
                "deals": [
                    {
                        "code": "FLIPNEW",
                        "discount": "25%",
                        "description": "25% off for new users",
                        "expiry": "2025-12-31",
                        "min_order": 0,
                    },
                    {
                        "code": "FLIPEXTRA",
                        "discount": "30%",
                        "description": "30% off on brands",
                        "expiry": "2025-12-31",
                        "min_order": 1000,
                    }
                ],
                "confidence": 0.92,
            },
        },
        "expected_decision": "CONTINUE",
        "expected_classification": ["FRESH", "EXTRA"],
        "expected_outcome": "completed",
        "should_retry": False,
    },
    {
        "id": "TC003",
        "name": "Swiggy - All deals match DB",
        "category": "happy_path",
        "merchant_id": "swiggy",
        "description": "Multiple deals all match perfectly between live and DB",
        "mock_responses": {
            "scraper": {
                "success": True,
                "html": '<div class="offer">SWIGGY40 - 40% off up to Rs 80</div>',
                "status_code": 200,
            },
            "db": {
                "deals": [
                    {
                        "code": "SWIGGY40",
                        "discount": "40%",
                        "description": "40% off up to Rs 80",
                        "expiry": "2025-12-31",
                        "min_order": 199,
                    }
                ]
            },
            "extractor": {
                "success": True,
                "deals": [
                    {
                        "code": "SWIGGY40",
                        "discount": "40%",
                        "description": "40% off up to Rs 80",
                        "expiry": "2025-12-31",
                        "min_order": 199,
                    }
                ],
                "confidence": 0.98,
            },
        },
        "expected_decision": "CONTINUE",
        "expected_classification": "FRESH",
        "expected_outcome": "completed",
        "should_retry": False,
    },
    {
        "id": "TC004",
        "name": "boAt - Minor description change but same discount",
        "category": "happy_path",
        "merchant_id": "boat",
        "description": "Deal matches except description wording (ignore description)",
        "mock_responses": {
            "scraper": {
                "success": True,
                "html": '<div class="deal">BOATSAVE - 15% discount on all earbuds</div>',
                "status_code": 200,
            },
            "db": {
                "deals": [
                    {
                        "code": "BOATSAVE",
                        "discount": "15%",
                        "description": "15% off on earbuds",
                        "expiry": "2025-12-31",
                        "min_order": 999,
                    }
                ]
            },
            "extractor": {
                "success": True,
                "deals": [
                    {
                        "code": "BOATSAVE",
                        "discount": "15%",
                        "description": "15% discount on all earbuds",
                        "expiry": "2025-12-31",
                        "min_order": 999,
                    }
                ],
                "confidence": 0.88,
            },
        },
        "expected_decision": "CONTINUE",
        "expected_classification": "FRESH",
        "expected_outcome": "completed",
        "should_retry": False,
    },
    {
        "id": "TC005",
        "name": "Domino's - Valid expiry and discount",
        "category": "happy_path",
        "merchant_id": "dominos",
        "description": "Deal found, discount matches, not expired",
        "mock_responses": {
            "scraper": {
                "success": True,
                "html": '<div class="coupon">DOM50 - Rs 50 off on pizza</div><span>Valid until 2025-12-31</span>',
                "status_code": 200,
            },
            "db": {
                "deals": [
                    {
                        "code": "DOM50",
                        "discount": "₹50 off",
                        "description": "Rs 50 off on pizza orders",
                        "expiry": "2025-12-31",
                        "min_order": 299,
                    }
                ]
            },
            "extractor": {
                "success": True,
                "deals": [
                    {
                        "code": "DOM50",
                        "discount": "₹50 off",
                        "description": "Rs 50 off on pizza",
                        "expiry": "2025-12-31",
                        "min_order": 299,
                    }
                ],
                "confidence": 0.9,
            },
        },
        "expected_decision": "CONTINUE",
        "expected_classification": "FRESH",
        "expected_outcome": "completed",
        "should_retry": False,
    },
    {
        "id": "TC006",
        "name": "Nykaa - Mixed fresh and extra deals",
        "category": "happy_path",
        "merchant_id": "nykaa",
        "description": "2 deals match DB, 1 is new extra deal",
        "mock_responses": {
            "scraper": {
                "success": True,
                "html": '<div class="promo">NYKAA20 - 20% off beauty</div><div class="promo">NYKAAFRESH - 25% off skincare</div>',
                "status_code": 200,
            },
            "db": {
                "deals": [
                    {
                        "code": "NYKAA20",
                        "discount": "20%",
                        "description": "20% off on beauty",
                        "expiry": "2025-09-30",
                        "min_order": 699,
                    }
                ]
            },
            "extractor": {
                "success": True,
                "deals": [
                    {
                        "code": "NYKAA20",
                        "discount": "20%",
                        "description": "20% off on beauty",
                        "expiry": "2025-09-30",
                        "min_order": 699,
                    },
                    {
                        "code": "NYKAAFRESH",
                        "discount": "25%",
                        "description": "25% off on skincare",
                        "expiry": "2025-12-31",
                        "min_order": 499,
                    }
                ],
                "confidence": 0.85,
            },
        },
        "expected_decision": "CONTINUE",
        "expected_classification": ["FRESH", "EXTRA"],
        "expected_outcome": "completed",
        "should_retry": False,
    },
    {
        "id": "TC007",
        "name": "BigBasket - Empty merchant (no deals anywhere)",
        "category": "happy_path",
        "merchant_id": "bigbasket",
        "description": "Merchant has no deals on live page, no deals in DB (clean state)",
        "mock_responses": {
            "scraper": {
                "success": True,
                "html": '<div class="merchant"><h1>BigBasket</h1><p>No active promotions</p></div>',
                "status_code": 200,
            },
            "db": {"deals": []},
            "extractor": {
                "success": True,
                "deals": [],
                "confidence": 1.0,
            },
        },
        "expected_decision": "CONTINUE",
        "expected_classification": [],
        "expected_outcome": "completed",
        "should_retry": False,
    },
    {
        "id": "TC008",
        "name": "CRED - Single deal exact match",
        "category": "happy_path",
        "merchant_id": "cred",
        "description": "Cleanest case: one deal in DB, one on live, perfect match",
        "mock_responses": {
            "scraper": {
                "success": True,
                "html": '<div class="offer">CREDCASH - Rs 200 cashback on bill payments</div>',
                "status_code": 200,
            },
            "db": {
                "deals": [
                    {
                        "code": "CREDCASH",
                        "discount": "₹200 off",
                        "description": "Rs 200 cashback on bill payments",
                        "expiry": "2025-12-31",
                        "min_order": 1000,
                    }
                ]
            },
            "extractor": {
                "success": True,
                "deals": [
                    {
                        "code": "CREDCASH",
                        "discount": "₹200 off",
                        "description": "Rs 200 cashback on bill payments",
                        "expiry": "2025-12-31",
                        "min_order": 1000,
                    }
                ],
                "confidence": 0.99,
            },
        },
        "expected_decision": "CONTINUE",
        "expected_classification": "FRESH",
        "expected_outcome": "completed",
        "should_retry": False,
    },
    {
        "id": "TC009",
        "name": "Tata CLiQ - Same discount, different min_order",
        "category": "happy_path",
        "merchant_id": "tatacliq",
        "description": "Deal match: discount same, min_order differs (ignore min_order for classification)",
        "mock_responses": {
            "scraper": {
                "success": True,
                "html": '<div class="coupon">TATA15 - 15% off Tata products</div>',
                "status_code": 200,
            },
            "db": {
                "deals": [
                    {
                        "code": "TATA15",
                        "discount": "15%",
                        "description": "15% off on Tata products",
                        "expiry": "2025-12-31",
                        "min_order": 1499,
                    }
                ]
            },
            "extractor": {
                "success": True,
                "deals": [
                    {
                        "code": "TATA15",
                        "discount": "15%",
                        "description": "15% off on Tata products",
                        "expiry": "2025-12-31",
                        "min_order": 999,  # Different but should still classify as FRESH
                    }
                ],
                "confidence": 0.91,
            },
        },
        "expected_decision": "CONTINUE",
        "expected_classification": "FRESH",
        "expected_outcome": "completed",
        "should_retry": False,
    },
    {
        "id": "TC010",
        "name": "Netmeds - Multiple deals all matching",
        "category": "happy_path",
        "merchant_id": "netmeds",
        "description": "3 deals in DB, 3 on live, all match perfectly",
        "mock_responses": {
            "scraper": {
                "success": True,
                "html": '<div class="offer">MED20 - 20% off medicines</div>',
                "status_code": 200,
            },
            "db": {
                "deals": [
                    {
                        "code": "MED20",
                        "discount": "20%",
                        "description": "20% off on medicines",
                        "expiry": "2025-12-31",
                        "min_order": 599,
                    }
                ]
            },
            "extractor": {
                "success": True,
                "deals": [
                    {
                        "code": "MED20",
                        "discount": "20%",
                        "description": "20% off on medicines",
                        "expiry": "2025-12-31",
                        "min_order": 599,
                    }
                ],
                "confidence": 0.97,
            },
        },
        "expected_decision": "CONTINUE",
        "expected_classification": "FRESH",
        "expected_outcome": "completed",
        "should_retry": False,
    },
    # ==================== FAILURE & RECOVERY (8 scenarios) ====================
    {
        "id": "TC011",
        "name": "Myntra - HTTP 403 fallback to google_cache",
        "category": "failure_recovery",
        "merchant_id": "myntra",
        "description": "Scraper returns 403 Forbidden → agent switches to google_cache → succeeds",
        "mock_responses": {
            "scraper": {
                "success": False,
                "error": "403 Forbidden",
                "error_type": "RATE_LIMIT",
                "status_code": 403,
            },
            "google_cache": {
                "success": True,
                "html": '<div class="deal">MYNTRA30 - 30% off fashion</div>',
                "status_code": 200,
            },
            "extractor": {
                "success": True,
                "deals": [
                    {
                        "code": "MYNTRA30",
                        "discount": "30%",
                        "description": "30% off on fashion",
                        "expiry": "2024-05-15",  # Expired
                        "min_order": 799,
                    }
                ],
                "confidence": 0.80,
            },
        },
        "expected_decision": "SWITCH_TOOL:google_cache",
        "expected_classification": "STALE",  # Expired
        "expected_outcome": "completed",
        "should_retry": True,
    },
    {
        "id": "TC012",
        "name": "Zomato - Timeout fallback to scrape_js",
        "category": "failure_recovery",
        "merchant_id": "zomato",
        "description": "HTTP scrape times out (30s) → agent switches to Playwright → succeeds",
        "mock_responses": {
            "scraper": {
                "success": False,
                "error": "Connection timeout",
                "error_type": "TIMEOUT",
                "latency_ms": 30000,
            },
            "scraper_js": {
                "success": True,
                "html": '<div class="coupon">ZOM100 - Flat Rs 100 off</div>',
                "status_code": 200,
                "latency_ms": 5000,
            },
            "extractor": {
                "success": True,
                "deals": [
                    {
                        "code": "ZOM100",
                        "discount": "₹100 off",
                        "description": "Flat Rs 100 off on orders above 299",
                        "expiry": "2025-12-31",
                        "min_order": 299,
                    }
                ],
                "confidence": 0.92,
            },
        },
        "expected_decision": "SWITCH_TOOL:scrape_js",
        "expected_classification": "FRESH",
        "expected_outcome": "completed",
        "should_retry": True,
    },
    {
        "id": "TC013",
        "name": "MakeMyTrip - JS scraper also fails → graceful degradation",
        "category": "failure_recovery",
        "merchant_id": "makemytrip",
        "description": "HTTP fails → JS fails → cache fails → graceful UNKNOWN status",
        "mock_responses": {
            "scraper": {
                "success": False,
                "error": "403 Forbidden",
                "error_type": "RATE_LIMIT",
            },
            "scraper_js": {
                "success": False,
                "error": "Browser timeout",
                "error_type": "TIMEOUT",
            },
            "google_cache": {
                "success": False,
                "error": "404 Not in cache",
                "error_type": "NOT_FOUND",
            },
        },
        "expected_decision": "MERCHANT_FAILED",
        "expected_classification": [],
        "expected_outcome": "error",
        "should_retry": False,
    },
    {
        "id": "TC014",
        "name": "unreliable_verifier - Retries with backoff succeed",
        "category": "failure_recovery",
        "merchant_id": "amazon",
        "description": "Verify coupon fails twice (transient), third attempt succeeds",
        "mock_responses": {
            "scraper": {
                "success": True,
                "html": '<div class="coupon">AMZNEW10 - 10% off</div>',
                "status_code": 200,
            },
            "db": {
                "deals": [
                    {
                        "code": "AMZNEW10",
                        "discount": "10%",
                        "description": "10% off on electronics",
                        "expiry": "2025-12-31",
                        "min_order": 500,
                    }
                ]
            },
            "extractor": {
                "success": True,
                "deals": [
                    {
                        "code": "AMZNEW10",
                        "discount": "10%",
                        "description": "10% off on electronics",
                        "expiry": "2025-12-31",
                        "min_order": 500,
                    }
                ],
                "confidence": 0.95,
            },
            "verify": {
                "retries": [
                    {"success": False, "error": "TimeoutError"},
                    {"success": False, "error": "ConnectionError"},
                    {"success": True, "is_active": True},
                ]
            },
        },
        "expected_decision": "RETRY",
        "expected_classification": "FRESH",
        "expected_outcome": "completed",
        "should_retry": True,
    },
    {
        "id": "TC015",
        "name": "extract_deals - Malformed JSON retry succeeds",
        "category": "failure_recovery",
        "merchant_id": "flipkart",
        "description": "LLM returns invalid JSON → agent retries with corrected prompt → succeeds",
        "mock_responses": {
            "scraper": {
                "success": True,
                "html": '<div class="coupon">FLIPNEW - 25% off</div>',
                "status_code": 200,
            },
            "extractor": {
                "retries": [
                    {
                        "success": False,
                        "error": "Invalid JSON: {'code': 'FLIPNEW'",
                        "error_type": "TRANSIENT",
                    },
                    {
                        "success": True,
                        "deals": [
                            {
                                "code": "FLIPNEW",
                                "discount": "25%",
                                "description": "25% off for new users",
                                "expiry": "2025-12-31",
                                "min_order": 0,
                            }
                        ],
                        "confidence": 0.93,
                    }
                ]
            },
            "db": {"deals": []},
        },
        "expected_decision": "RETRY",
        "expected_classification": "EXTRA",
        "expected_outcome": "completed",
        "should_retry": True,
    },
    {
        "id": "TC016",
        "name": "google_cache also blocked → merchant error",
        "category": "failure_recovery",
        "merchant_id": "ajio",
        "description": "Scraper blocked → cache also blocked → mark merchant ERROR",
        "mock_responses": {
            "scraper": {
                "success": False,
                "error": "403 Forbidden",
                "error_type": "RATE_LIMIT",
            },
            "google_cache": {
                "success": False,
                "error": "403 Forbidden from cache service",
                "error_type": "RATE_LIMIT",
            },
        },
        "expected_decision": "MERCHANT_FAILED",
        "expected_classification": [],
        "expected_outcome": "error",
        "should_retry": False,
    },
    {
        "id": "TC017",
        "name": "db_lookup - Empty DB, live deals marked EXTRA",
        "category": "failure_recovery",
        "merchant_id": "meesho",
        "description": "DB is empty (merchant not in database) → all live deals classified as EXTRA",
        "mock_responses": {
            "scraper": {
                "success": True,
                "html": '<div class="deal">MEESHO99 - Rs 99 off on first order</div>',
                "status_code": 200,
            },
            "db": {"deals": []},
            "extractor": {
                "success": True,
                "deals": [
                    {
                        "code": "MEESHO99",
                        "discount": "₹99 off",
                        "description": "Rs 99 off on first order",
                        "expiry": "2024-12-31",  # Expired
                        "min_order": 0,
                    }
                ],
                "confidence": 0.88,
            },
        },
        "expected_decision": "CONTINUE",
        "expected_classification": "EXTRA",  # All deals are extra if DB empty
        "expected_outcome": "completed",
        "should_retry": False,
    },
    {
        "id": "TC018",
        "name": "scrape_html empty → try scrape_js → succeeds",
        "category": "failure_recovery",
        "merchant_id": "blinkit",
        "description": "HTTP scraper returns empty HTML → switch to Playwright → find deals",
        "mock_responses": {
            "scraper": {
                "success": True,
                "html": "",  # Empty
                "status_code": 200,
            },
            "scraper_js": {
                "success": True,
                "html": '<div class="offer">BLINK50 - Rs 50 off on groceries</div>',
                "status_code": 200,
            },
            "db": {
                "deals": [
                    {
                        "code": "BLINK50",
                        "discount": "₹50 off",
                        "description": "Rs 50 off on groceries",
                        "expiry": "2025-12-31",
                        "min_order": 299,
                    }
                ]
            },
            "extractor": {
                "success": True,
                "deals": [
                    {
                        "code": "BLINK50",
                        "discount": "₹50 off",
                        "description": "Rs 50 off on groceries",
                        "expiry": "2025-12-31",
                        "min_order": 299,
                    }
                ],
                "confidence": 0.91,
            },
        },
        "expected_decision": "SWITCH_TOOL:scrape_js",
        "expected_classification": "FRESH",
        "expected_outcome": "completed",
        "should_retry": True,
    },
    # ==================== BUDGET EXCEEDED (4 scenarios) ====================
    {
        "id": "TC019",
        "name": "Budget - max_tool_calls=5 exceeded at call 6",
        "category": "budget_exceeded",
        "merchant_id": "amazon",
        "description": "Budget limit: 5 tool calls. Task needs 6. Agent halts after 5.",
        "mock_responses": None,
        "expected_decision": "BUDGET_EXCEEDED",
        "expected_classification": [],
        "expected_outcome": "budget_exceeded",
        "should_retry": False,
        "budget_config": {
            "max_tool_calls": 5,
            "max_tokens_per_run": 999999,
            "max_wall_clock_seconds": 999,
        },
    },
    {
        "id": "TC020",
        "name": "Budget - max_tokens=1000 normal task exceeds",
        "category": "budget_exceeded",
        "merchant_id": "myntra",
        "description": "Token limit is 1000. Normal audit uses more. Agent halts mid-merchant.",
        "mock_responses": None,
        "expected_decision": "BUDGET_EXCEEDED",
        "expected_classification": [],
        "expected_outcome": "budget_exceeded",
        "should_retry": False,
        "budget_config": {
            "max_tool_calls": 999,
            "max_tokens_per_run": 1000,
            "max_wall_clock_seconds": 999,
        },
    },
    {
        "id": "TC021",
        "name": "Budget - max_wall_clock=10s exceeded",
        "category": "budget_exceeded",
        "merchant_id": "zomato",
        "description": "Time limit is 10s. Normal audit takes longer. Agent halts after 10s.",
        "mock_responses": None,
        "expected_decision": "BUDGET_EXCEEDED",
        "expected_classification": [],
        "expected_outcome": "budget_exceeded",
        "should_retry": False,
        "budget_config": {
            "max_tool_calls": 999,
            "max_tokens_per_run": 999999,
            "max_wall_clock_seconds": 10,
        },
    },
    {
        "id": "TC022",
        "name": "Budget - max_consecutive_failures=2 exceeded at 3rd",
        "category": "budget_exceeded",
        "merchant_id": "swiggy",
        "description": "3 consecutive failures with max=2. Agent halts after 3rd failure.",
        "mock_responses": {
            "scraper": {"success": False, "error_type": "PERMANENT"},
            "scraper_js": {"success": False, "error_type": "PERMANENT"},
            "google_cache": {"success": False, "error_type": "PERMANENT"},
        },
        "expected_decision": "MAX_CONSECUTIVE_FAILURES",
        "expected_classification": [],
        "expected_outcome": "budget_exceeded",
        "should_retry": False,
        "budget_config": {
            "max_tool_calls": 999,
            "max_tokens_per_run": 999999,
            "max_wall_clock_seconds": 999,
            "max_consecutive_failures": 2,
        },
    },
    # ==================== EDGE CASES / IMPOSSIBLE (4 scenarios) ====================
    {
        "id": "TC023",
        "name": "Edge - Page permanently 404",
        "category": "edge_cases",
        "merchant_id": "puma",
        "description": "All scraping attempts return 404 permanently. Market item removed.",
        "mock_responses": {
            "scraper": {
                "success": False,
                "error": "404 Not Found",
                "error_type": "NOT_FOUND",
            },
            "google_cache": {
                "success": False,
                "error": "404 Not Found",
                "error_type": "NOT_FOUND",
            },
            "scraper_js": {
                "success": False,
                "error": "404 Not Found",
                "error_type": "NOT_FOUND",
            },
        },
        "expected_decision": "MERCHANT_FAILED",
        "expected_classification": [],
        "expected_outcome": "error",
        "should_retry": False,
    },
    {
        "id": "TC024",
        "name": "Edge - All tools blocked for merchant",
        "category": "edge_cases",
        "merchant_id": "cred",
        "description": "Merchant site fully blocked. All tools fail. No retry helps.",
        "mock_responses": {
            "scraper": {"success": False, "error_type": "RATE_LIMIT"},
            "google_cache": {"success": False, "error_type": "RATE_LIMIT"},
            "scraper_js": {"success": False, "error_type": "RATE_LIMIT"},
        },
        "expected_decision": "MERCHANT_FAILED",
        "expected_classification": [],
        "expected_outcome": "error",
        "should_retry": False,
    },
    {
        "id": "TC025",
        "name": "Edge - LLM hallucination detection",
        "category": "edge_cases",
        "merchant_id": "boat",
        "description": "LLM returns coupon codes that don't appear in HTML. Confidence < 0.3.",
        "mock_responses": {
            "scraper": {
                "success": True,
                "html": '<div>boAt products</div>',  # No coupon codes visible
                "status_code": 200,
            },
            "extractor": {
                "success": True,
                "deals": [
                    {
                        "code": "BOATFAKE1",
                        "discount": "50%",
                        "description": "Made-up coupon",
                        "expiry": "2025-12-31",
                        "min_order": 0,
                    }
                ],
                "confidence": 0.15,  # Low confidence = hallucinated
            },
        },
        "expected_decision": "CONTINUE",  # Agent proceeds but flags low confidence
        "expected_classification": [],
        "expected_outcome": "completed",
        "should_retry": False,
    },
    {
        "id": "TC026",
        "name": "Edge - Merchant with 0 deals everywhere",
        "category": "edge_cases",
        "merchant_id": "dominos",
        "description": "0 deals on live, 0 in DB. Classified as CLEAN, not error.",
        "mock_responses": {
            "scraper": {
                "success": True,
                "html": '<div><h1>Dominos</h1><p>No current offers</p></div>',
                "status_code": 200,
            },
            "db": {"deals": []},
            "extractor": {
                "success": True,
                "deals": [],
                "confidence": 1.0,
            },
        },
        "expected_decision": "CONTINUE",
        "expected_classification": [],
        "expected_outcome": "completed",
        "should_retry": False,
    },
    # ==================== MULTI-LLM ROUTING (4 scenarios) ====================
    {
        "id": "TC027",
        "name": "Multi-LLM - Groq rate limit → OpenRouter fallback",
        "category": "multi_llm",
        "merchant_id": "amazon",
        "description": "Groq rate limited during PLANNING → router falls back to OpenRouter",
        "mock_responses": {
            "planner": {
                "provider_sequence": ["groq", "openrouter"],
                "groq": {"success": False, "error": "429 Rate limit"},
                "openrouter": {"success": True, "plan": "default"},
            }
        },
        "expected_decision": "CONTINUE",
        "expected_classification": "FRESH",
        "expected_outcome": "completed",
        "should_retry": True,
    },
    {
        "id": "TC028",
        "name": "Multi-LLM - Gemini timeout → Groq fallback",
        "category": "multi_llm",
        "merchant_id": "myntra",
        "description": "Gemini Flash times out during EXTRACTION → router uses Groq",
        "mock_responses": {
            "extractor": {
                "provider_sequence": ["gemini", "groq"],
                "gemini": {"success": False, "error": "Timeout"},
                "groq": {
                    "success": True,
                    "deals": [
                        {
                            "code": "MYNTRA30",
                            "discount": "30%",
                            "description": "30% off",
                            "expiry": "2025-12-31",
                            "min_order": 799,
                        }
                    ],
                    "confidence": 0.88,
                },
            }
        },
        "expected_decision": "CONTINUE",
        "expected_classification": "FRESHorSTALE",  # Depends on actual expiry
        "expected_outcome": "completed",
        "should_retry": True,
    },
    {
        "id": "TC029",
        "name": "Multi-LLM - Cost tracking verified",
        "category": "multi_llm",
        "merchant_id": "flipkart",
        "description": "Full audit routes through Groq/Gemini/OpenRouter. Verify cost calc.",
        "mock_responses": {
            "planner": {"provider": "groq", "tokens": 1200, "cost": 0.00006},
            "extractor": {"provider": "gemini", "tokens": 2800, "cost": 0.00084},
            "verifier": {"provider": "openrouter", "tokens": 150, "cost": 0.000015},
        },
        "expected_decision": "CONTINUE",
        "expected_classification": "FRESH",
        "expected_outcome": "completed",
        "should_retry": False,
    },
    {
        "id": "TC030",
        "name": "Multi-LLM - Cheap model for simple classification",
        "category": "multi_llm",
        "merchant_id": "zomato",
        "description": "CLASSIFICATION task routes to 8b model (cheaper). Verify savings.",
        "mock_responses": {
            "classifier": {
                "provider": "groq_8b",  # Cheap model
                "tokens": 400,
                "cost": 0.00002,
            }
        },
        "expected_decision": "CONTINUE",
        "expected_classification": "FRESH",
        "expected_outcome": "completed",
        "should_retry": False,
    },
]


def get_scenario(scenario_id: str) -> Optional[Dict[str, Any]]:
    """
    Get a single scenario by ID.
    
    Args:
        scenario_id: Scenario ID like "TC001"
        
    Returns:
        Scenario dict or None if not found
    """
    for scenario in SCENARIOS:
        if scenario["id"] == scenario_id:
            return scenario
    return None


def get_scenarios_by_category(category: str) -> List[Dict[str, Any]]:
    """
    Get all scenarios in a category.
    
    Args:
        category: Category name (happy_path, failure_recovery, etc.)
        
    Returns:
        List of scenario dicts
    """
    return [s for s in SCENARIOS if s["category"] == category]


def get_all_scenarios() -> List[Dict[str, Any]]:
    """Get all scenarios."""
    return SCENARIOS.copy()
