"""kopf handlers: reconcile Tenant custom resources into real cluster objects.

Run locally against the current kubeconfig context:
    kopf run --standalone -m tenant_operator.handlers
"""

from __future__ import annotations

import logging
import time

import kopf
from kubernetes import config, dynamic
from kubernetes.client import api_client
from kubernetes.client.exceptions import ApiException
from kubernetes.dynamic.exceptions import NotFoundError

from . import metrics
from .resources import (
    GROUP,
    MANAGED_BY,
    VERSION,
    TenantSpecError,
    build_all,
    namespace_is_ours,
    parse_spec,
)

PLURAL = "tenants"
DRIFT_INTERVAL_SECONDS = 300

_client: dynamic.DynamicClient | None = None
_known_tenants: set[str] = set()


def _dyn() -> dynamic.DynamicClient:
    global _client
    if _client is None:
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()
        _client = dynamic.DynamicClient(api_client.ApiClient())
    return _client


def _apply(obj: dict) -> None:
    """Server-side apply, so the operator owns exactly the fields it sets."""
    client = _dyn()
    api = client.resources.get(api_version=obj["apiVersion"], kind=obj["kind"])
    client.server_side_apply(
        api,
        body=obj,
        name=obj["metadata"]["name"],
        namespace=obj["metadata"].get("namespace"),
        field_manager=MANAGED_BY,
        force_conflicts=True,
    )


def _guard_existing_namespace(name: str) -> None:
    """Refuse to adopt a namespace this operator did not create (defence in depth next to the
    ValidatingAdmissionPolicy in deploy/admission-policy.yaml)."""
    client = _dyn()
    api = client.resources.get(api_version="v1", kind="Namespace")
    try:
        existing = api.get(name=name).to_dict()
    except NotFoundError:
        return
    labels = existing.get("metadata", {}).get("labels")
    if not namespace_is_ours(labels, name):
        metrics.RECONCILES.labels(result="refused").inc()
        raise kopf.PermanentError(f"namespace {name!r} already exists and is not managed by {MANAGED_BY}")


def _reconcile(name: str, spec: dict, body: kopf.Body, logger: logging.Logger) -> dict:
    started = time.monotonic()
    try:
        tenant = parse_spec(name, spec)
    except TenantSpecError as err:
        metrics.RECONCILES.labels(result="invalid_spec").inc()
        # Permanent: retrying will not fix a bad spec, the user must edit it.
        raise kopf.PermanentError(str(err)) from err

    _guard_existing_namespace(tenant.name)
    objects = build_all(tenant)
    for obj in objects:
        # Cluster-scoped Tenant owns everything, so deleting it garbage-collects the namespace.
        kopf.adopt(obj, owner=body)
        try:
            _apply(obj)
        except ApiException as err:
            metrics.RECONCILES.labels(result="api_error").inc()
            raise kopf.TemporaryError(
                f"applying {obj['kind']}/{obj['metadata']['name']} failed: {err.reason}",
                delay=30,
            ) from err

    metrics.RECONCILE_SECONDS.observe(time.monotonic() - started)
    metrics.RECONCILES.labels(result="success").inc()
    _known_tenants.add(name)
    metrics.TENANTS.set(len(_known_tenants))
    logger.info("tenant %s reconciled: %d objects applied", name, len(objects))
    return {"phase": "Ready", "objects": len(objects), "observedGeneration": body.meta.get("generation")}


@kopf.on.startup()
def startup(settings: kopf.OperatorSettings, **_) -> None:
    settings.persistence.finalizer = f"{GROUP}/finalizer"
    settings.posting.level = logging.WARNING
    metrics.serve(8080)


@kopf.on.create(GROUP, VERSION, PLURAL)
@kopf.on.update(GROUP, VERSION, PLURAL)
@kopf.on.resume(GROUP, VERSION, PLURAL)
def reconcile(name, spec, body, logger, **_):
    return _reconcile(name, spec, body, logger)


@kopf.timer(GROUP, VERSION, PLURAL, interval=DRIFT_INTERVAL_SECONDS, initial_delay=60, idle=60)
def drift_check(name, spec, body, logger, **_):
    """Re-apply desired state; server-side apply is a no-op when nothing drifted."""
    try:
        tenant = parse_spec(name, spec)
    except TenantSpecError:
        return  # the create/update handler already reported this
    try:
        _guard_existing_namespace(tenant.name)
    except kopf.PermanentError:
        return  # never touch a namespace we do not own
    for obj in build_all(tenant):
        kopf.adopt(obj, owner=body)
        _apply(obj)
        metrics.DRIFT_APPLIES.inc()
    logger.debug("drift check done for %s", name)


@kopf.on.delete(GROUP, VERSION, PLURAL)
def deleted(name, logger, **_):
    # Owner references make the API server garbage-collect the namespace.
    _known_tenants.discard(name)
    metrics.TENANTS.set(len(_known_tenants))
    logger.info("tenant %s deleted; namespace will be garbage-collected", name)


@kopf.on.probe(id="tenants")
def probe_tenants(**_):
    return len(_known_tenants)
