from prometheus_client import Counter, Histogram, generate_latest

HTTP_REQUESTS = Counter(
    "banorte_http_requests_total",
    "HTTP requests",
    ["method", "path", "status"],
)
HTTP_LATENCY = Histogram(
    "banorte_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "path"],
)
OPENAI_CALLS = Counter("banorte_openai_calls_total", "OpenAI calls", ["status"])
OPENAI_LATENCY = Histogram(
    "banorte_openai_call_duration_seconds",
    "OpenAI call latency",
    ["status"],
)
SEARCH_HITS = Histogram(
    "banorte_wiki_search_hits",
    "Relevant wiki pages returned per search",
    buckets=(0, 1, 2, 3, 5, 10),
)
INGEST_EVENTS = Counter("banorte_ingest_events_total", "Ingest events", ["status"])


def render_metrics() -> bytes:
    return generate_latest()
