"""
Test scenarios for GrabOn audit agent evaluation suite.

Defines 15 essential test cases covering:
- Happy path scenarios (exact match, extra deals, empty merchant)
- Failure and recovery (HTTP 403, timeouts, retries)
- Budget enforcement (token limits, time limits)
- Edge cases (404 pages, zero deals)
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
    # ==================== HAPPY PATH (5 scenarios: TC001, TC002, TC006, TC007, TC010) ====================
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
    # ==================== FAILURE & RECOVERY (4 scenarios: TC011, TC012, TC014, TC015) ====================
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

    # ==================== BUDGET EXCEEDED (2 scenarios: TC020, TC022) ====================

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
    # ==================== EDGE CASES / IMPOSSIBLE (2 scenarios: TC023, TC025) ====================
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

    # ==================== MULTI-LLM ROUTING (2 scenarios: TC028, TC030) ====================
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
