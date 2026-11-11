"""Prometheus metrics: request latency, background jobs, the live price stream and simulated trading.

The API serves them at /metrics and the worker on WORKER_METRICS_PORT. Counters are per process,
so Prometheus should scrape every instance (see deploy/prometheus.yml); sum() across instances.
Labels are kept to small, fixed sets (route templates, not raw paths) so cardinality stays bounded.
"""

import hmac
import threading
from collections.abc import Callable, Iterable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily, Metric
from prometheus_client.platform_collector import PlatformCollector
from prometheus_client.process_collector import ProcessCollector
from prometheus_client.registry import Collector

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"

REGISTRY = CollectorRegistry()
ProcessCollector(registry=REGISTRY)  # CPU, memory, open files (Linux only; a no-op elsewhere)
PlatformCollector(registry=REGISTRY)

HTTP_REQUESTS = Counter(
    "kestrel_http_requests_total", "HTTP requests by route template and status", ["method", "route", "status"], registry=REGISTRY
)
HTTP_LATENCY = Histogram(
    "kestrel_http_request_duration_seconds",
    "HTTP request latency by route template",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
    registry=REGISTRY,
)
JOB_RUNS = Counter("kestrel_background_job_runs_total", "Background job runs by outcome", ["job", "outcome"], registry=REGISTRY)
JOB_DURATION = Histogram(
    "kestrel_background_job_duration_seconds",
    "Background job run time",
    ["job"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300),
    registry=REGISTRY,
)
JOB_LAST_SUCCESS = Gauge(
    "kestrel_background_job_last_success_timestamp_seconds",
    "Unix time of the job's last successful run",
    ["job"],
    registry=REGISTRY,
)
PAPER_ORDERS = Counter(
    "kestrel_paper_orders_total",
    "Simulated paper orders by who placed them and their status after placement",
    ["source", "side", "status"],
    registry=REGISTRY,
)
PAPER_FILLS = Counter("kestrel_paper_fills_total", "Simulated paper order fills", ["side"], registry=REGISTRY)
MARGIN_CALLS = Counter("kestrel_paper_margin_calls_total", "Shorts force-covered by a simulated margin call", registry=REGISTRY)
ALERT_EVENTS = Counter("kestrel_alert_events_total", "Strategy alert events recorded", ["kind"], registry=REGISTRY)
EMAILS = Counter("kestrel_emails_total", "Outgoing email by outcome", ["outcome"], registry=REGISTRY)


class StateCollector(Collector):
    """Reads live state (stream health, leadership, websocket clients) at scrape time."""

    def __init__(self, fn: Callable[[], Iterable[Metric]]) -> None:
        self.fn = fn

    def collect(self) -> Iterable[Metric]:
        return list(self.fn())


def register_state(fn: Callable[[], Iterable[Metric]]) -> None:
    REGISTRY.register(StateCollector(fn))


def gauge(name: str, doc: str, value: float) -> GaugeMetricFamily:
    return GaugeMetricFamily(name, doc, value=value)


def counter(name: str, doc: str, value: float) -> CounterMetricFamily:
    return CounterMetricFamily(name, doc, value=value)


def render() -> bytes:
    return generate_latest(REGISTRY)


def serve_metrics(port: int, token: str | None = None, host: str = "0.0.0.0") -> ThreadingHTTPServer | None:
    """Serve /metrics from a background thread (for the worker, which has no web app). Port 0 disables it."""
    if port <= 0:
        return None

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path.split("?")[0] != "/metrics":
                self.send_response(404)
                self.end_headers()
                return
            sent = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
            if token and not hmac.compare_digest(sent.encode(), token.encode()):
                self.send_response(401)
                self.send_header("WWW-Authenticate", "Bearer")
                self.end_headers()
                return
            body = render()
            self.send_response(200)
            self.send_header("Content-Type", CONTENT_TYPE)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:  # scrapes every 15s would flood the log
            pass

    server = ThreadingHTTPServer((host, port), Handler)
    threading.Thread(target=server.serve_forever, name="metrics-http", daemon=True).start()
    return server
