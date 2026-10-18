"""Pure builders that turn a Tenant spec into Kubernetes objects.

Nothing in this module talks to the API server, so every rule here is
covered by fast unit tests. The kopf handlers only apply what these
functions return.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

GROUP = "platform.example.io"
VERSION = "v1alpha1"
MANAGED_BY = "tenant-operator"
MANAGED_BY_LABEL = "app.kubernetes.io/managed-by"
TENANT_LABEL = f"{GROUP}/tenant"

# Never hand these to a tenant: adopting one would let a Tenant delete it via garbage collection.
RESERVED_NAMESPACES = frozenset(
    {"default", "kube-system", "kube-public", "kube-node-lease", "tenant-operator", "monitoring", "istio-system"}
)

_DNS1123 = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
# Kubernetes quantity: number with optional binary/decimal suffix (e.g. 500m, 4, 16Gi, 1Ti)
_QUANTITY = re.compile(r"^[0-9]+(\.[0-9]+)?(m|k|M|G|T|P|Ki|Mi|Gi|Ti|Pi)?$")


class TenantSpecError(ValueError):
    """Raised when a Tenant spec cannot be turned into resources."""


@dataclass(frozen=True)
class StorageQuota:
    storage_class: str
    requests: str
    max_claims: int = 10


@dataclass(frozen=True)
class TenantSpec:
    name: str
    owners_group: str
    cpu: str = "4"
    memory: str = "16Gi"
    gpus: int = 0
    storage: tuple[StorageQuota, ...] = field(default_factory=tuple)
    mesh_enabled: bool = False
    monitoring_namespace: str = "monitoring"


def parse_spec(name: str, spec: dict) -> TenantSpec:
    """Validate the raw custom-resource spec and return a typed TenantSpec."""
    if not name or len(name) > 63 or not _DNS1123.match(name):
        raise TenantSpecError(f"tenant name {name!r} is not a valid DNS-1123 label")
    if name in RESERVED_NAMESPACES or name.startswith("kube-"):
        raise TenantSpecError(f"tenant name {name!r} is reserved for the platform")

    owners = spec.get("ownersGroup")
    if not owners:
        raise TenantSpecError("spec.ownersGroup is required")

    quota = spec.get("quota", {})
    cpu = str(quota.get("cpu", "4"))
    memory = str(quota.get("memory", "16Gi"))
    for label, value in (("cpu", cpu), ("memory", memory)):
        if not _QUANTITY.match(value):
            raise TenantSpecError(f"spec.quota.{label} {value!r} is not a valid quantity")

    gpus = quota.get("gpus", 0)
    if not isinstance(gpus, int) or isinstance(gpus, bool) or gpus < 0:
        raise TenantSpecError("spec.quota.gpus must be a non-negative integer")

    storage: list[StorageQuota] = []
    seen: set[str] = set()
    for item in spec.get("storage", []):
        sc = item.get("storageClass", "")
        req = str(item.get("requests", ""))
        claims = item.get("maxClaims", 10)
        if not _DNS1123.match(sc):
            raise TenantSpecError(f"storageClass {sc!r} is not a valid name")
        if sc in seen:
            raise TenantSpecError(f"storageClass {sc!r} listed twice")
        if not _QUANTITY.match(req):
            raise TenantSpecError(f"storage requests {req!r} for {sc} is not a valid quantity")
        if not isinstance(claims, int) or claims < 1:
            raise TenantSpecError(f"maxClaims for {sc} must be a positive integer")
        seen.add(sc)
        storage.append(StorageQuota(sc, req, claims))

    mesh = spec.get("mesh", {}).get("enabled", False)
    return TenantSpec(
        name=name,
        owners_group=owners,
        cpu=cpu,
        memory=memory,
        gpus=gpus,
        storage=tuple(storage),
        mesh_enabled=bool(mesh),
        monitoring_namespace=spec.get("monitoringNamespace", "monitoring"),
    )


def namespace_is_ours(labels: dict | None, tenant: str) -> bool:
    """True if an existing namespace was created by this operator for this tenant."""
    labels = labels or {}
    return labels.get(MANAGED_BY_LABEL) == MANAGED_BY and labels.get(TENANT_LABEL) == tenant


def _labels(t: TenantSpec) -> dict:
    return {
        MANAGED_BY_LABEL: MANAGED_BY,
        TENANT_LABEL: t.name,
    }


def namespace(t: TenantSpec) -> dict:
    labels = _labels(t)
    labels["pod-security.kubernetes.io/enforce"] = "restricted"
    # Istio sidecar injection is opt-in per tenant.
    labels["istio-injection"] = "enabled" if t.mesh_enabled else "disabled"
    return {
        "apiVersion": "v1",
        "kind": "Namespace",
        "metadata": {"name": t.name, "labels": labels},
    }


def resource_quota(t: TenantSpec) -> dict:
    hard = {
        "requests.cpu": t.cpu,
        "requests.memory": t.memory,
        "limits.cpu": t.cpu,
        "limits.memory": t.memory,
        # GPUs are an extended resource: only requests can be quota'd.
        "requests.nvidia.com/gpu": str(t.gpus),
    }
    total_claims = 0
    for s in t.storage:
        prefix = f"{s.storage_class}.storageclass.storage.k8s.io"
        hard[f"{prefix}/requests.storage"] = s.requests
        hard[f"{prefix}/persistentvolumeclaims"] = str(s.max_claims)
        total_claims += s.max_claims
    # Block PVCs on any storage class the tenant was not given.
    hard["persistentvolumeclaims"] = str(total_claims)
    return {
        "apiVersion": "v1",
        "kind": "ResourceQuota",
        "metadata": {"name": "tenant-quota", "namespace": t.name, "labels": _labels(t)},
        "spec": {"hard": hard},
    }


def limit_range(t: TenantSpec) -> dict:
    """Defaults so pods without requests still count against the quota."""
    return {
        "apiVersion": "v1",
        "kind": "LimitRange",
        "metadata": {"name": "tenant-defaults", "namespace": t.name, "labels": _labels(t)},
        "spec": {
            "limits": [
                {
                    "type": "Container",
                    "defaultRequest": {"cpu": "100m", "memory": "128Mi"},
                    "default": {"cpu": "500m", "memory": "512Mi"},
                }
            ]
        },
    }


def network_policies(t: TenantSpec) -> list[dict]:
    meta = {"namespace": t.name, "labels": _labels(t)}
    deny_all = {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {"name": "default-deny-ingress", **meta},
        "spec": {"podSelector": {}, "policyTypes": ["Ingress"]},
    }
    same_ns = {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {"name": "allow-same-namespace", **meta},
        "spec": {
            "podSelector": {},
            "policyTypes": ["Ingress"],
            "ingress": [{"from": [{"podSelector": {}}]}],
        },
    }
    scrape = {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {"name": "allow-prometheus-scrape", **meta},
        "spec": {
            "podSelector": {},
            "policyTypes": ["Ingress"],
            "ingress": [
                {
                    "from": [
                        {
                            "namespaceSelector": {
                                "matchLabels": {
                                    "kubernetes.io/metadata.name": t.monitoring_namespace
                                }
                            }
                        }
                    ]
                }
            ],
        },
    }
    return [deny_all, same_ns, scrape]


def owners_role_binding(t: TenantSpec) -> dict:
    return {
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "kind": "RoleBinding",
        "metadata": {"name": "tenant-owners", "namespace": t.name, "labels": _labels(t)},
        "roleRef": {
            "apiGroup": "rbac.authorization.k8s.io",
            "kind": "ClusterRole",
            "name": "edit",
        },
        "subjects": [
            {
                "apiGroup": "rbac.authorization.k8s.io",
                "kind": "Group",
                "name": t.owners_group,
            }
        ],
    }


def build_all(t: TenantSpec) -> list[dict]:
    """Every object a tenant owns, namespace first so later applies succeed."""
    return [
        namespace(t),
        resource_quota(t),
        limit_range(t),
        *network_policies(t),
        owners_role_binding(t),
    ]
