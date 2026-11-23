"""Application metrics, exposed on /metrics alongside the HTTP instrumentator's."""

from prometheus_client import Counter, Histogram

RETRIEVAL_SECONDS = Histogram(
    "gabriella_retrieval_seconds",
    "Catalogue retrieval latency (filters + lexical + vector + fusion)",
    ["mode"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5),
)
SEARCH_RESULTS = Counter(
    "gabriella_search_total",
    "Searches by result quality: exact (lexical hits), related (vector only), none",
    ["match"],
)
SIMILAR_SECONDS = Histogram(
    "gabriella_similar_seconds",
    "Similar-product retrieval latency",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1),
)
AGENT_TURNS = Counter(
    "gabriella_agent_turns_total",
    "Chat turns by mode (llm | fallback) and outcome (ok | error)",
    ["mode", "outcome"],
)
AGENT_TURN_SECONDS = Histogram(
    "gabriella_agent_turn_seconds",
    "End-to-end chat turn latency",
    ["mode"],
    buckets=(0.1, 0.25, 0.5, 1, 2, 4, 8, 15, 30, 60),
)
RECOMMENDED_ITEMS = Counter(
    "gabriella_recommended_items_total",
    "Validated product cards shown to shoppers",
    ["mode"],
)
