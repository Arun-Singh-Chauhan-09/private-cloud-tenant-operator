# Runbook: tenant-operator

## TenantOperatorDown

**Impact:** new tenants and spec changes are not applied; existing namespaces keep working.

1. `kubectl -n tenant-operator get pods` — crash-looping, pending, or gone?
2. `kubectl -n tenant-operator logs deploy/tenant-operator --previous` for the crash reason.
3. Pending: check node capacity and the namespace's Pod Security level.
4. If the pod is running but not scraped, check the ServiceMonitor selector and the `metrics` port.

## TenantReconcileErrors

**Impact:** some tenant objects are stale or missing.

1. `kubectl get tenants` — which ones are not `Ready`?
2. `kubectl describe tenant <name>` — kopf posts the API error as an event.
3. Forbidden → the operator's ClusterRole is missing a verb or resource; diff `deploy/rbac.yaml` with the cluster.
4. Conflict or timeout → check API server health; kopf retries every 30s on its own.

## TenantInvalidSpec

**Impact:** one team's tenant was not created or updated. Informational.

1. `kubectl describe tenant <name>` shows the validation message (bad quantity, duplicate storage class, missing owners group).
2. Ask the owning team to fix the spec; the operator does not retry invalid specs.

## TenantReconcileSlow

**Impact:** onboarding takes longer; usually a symptom of API server latency.

1. Check API server request latency dashboards.
2. Check whether many tenants were applied at once (bulk import) — that settles on its own.
