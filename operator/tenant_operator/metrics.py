"""Prometheus metrics exposed by the operator on :8080/metrics."""

from prometheus_client import Counter, Gauge, Histogram, start_http_server

RECONCILES = Counter(
    "tenant_operator_reconciles_total",
    "Tenant reconciliations by result.",
    ["result"],  # success | invalid_spec | refused | api_error
)
RECONCILE_SECONDS = Histogram(
    "tenant_operator_reconcile_duration_seconds",
    "Time spent applying a tenant's resources.",
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
DRIFT_APPLIES = Counter(
    "tenant_operator_drift_applies_total",
    "Objects re-applied by the periodic drift check (no-op when nothing drifted).",
)
TENANTS = Gauge(
    "tenant_operator_tenants",
    "Tenants currently known to the operator.",
)


def serve(port: int = 8080) -> None:
    start_http_server(port)
