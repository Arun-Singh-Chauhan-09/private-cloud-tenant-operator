# private-cloud-tenant-operator

A small slice of what a platform team on a **private, bare-metal Kubernetes cloud** does:
onboard product teams safely, with quotas for CPU, memory, **persistent storage** and **GPUs**,
default-deny networking, optional **Istio** sidecar injection, and nodes prepared by **Puppet**.
Delivery runs through **GitLab CI**, and the operator exports **Prometheus** metrics with alert rules and a runbook.

```
            kubectl apply Tenant                     Puppet (k8s_node module)
                    │                                         │
                    ▼                                         ▼
 ┌──────────────────────────────────┐         bare-metal hosts: kernel modules,
 │ tenant-operator (Python / kopf)  │         sysctls, swap off, containerd
 │  validate spec → build objects → │         (systemd cgroups, NVIDIA runtime
 │  server-side apply → status      │          on GPU nodes), pinned kubelet
 │  drift check every 5 min         │
 │  /metrics → Prometheus           │
 └──────────────┬───────────────────┘
                ▼
   Namespace team-x  (PSA restricted, istio-injection on/off, owned by the Tenant)
     ├─ ResourceQuota  cpu · memory · nvidia.com/gpu · per-StorageClass storage + PVC count
     ├─ LimitRange     default requests/limits so every pod counts against quota
     ├─ NetworkPolicy  default-deny · allow same namespace · allow Prometheus scrape
     └─ RoleBinding    team's IdP group → ClusterRole edit
```

## Why an operator and not a Helm chart

A chart renders once. Tenants change: a team asks for two more GPUs, someone deletes a quota by hand,
a namespace needs mesh enabled. The operator owns the desired state, re-applies it with server-side apply
(so it only fights over the fields it manages), and deleting the `Tenant` garbage-collects everything through
owner references.

## Tenant API

```yaml
apiVersion: platform.example.io/v1alpha1
kind: Tenant
metadata:
  name: team-ml
spec:
  ownersGroup: team-ml-devs        # bound to ClusterRole edit
  quota: {cpu: "32", memory: 128Gi, gpus: 4}
  storage:                         # PVCs are blocked on any class not listed
    - {storageClass: ceph-rbd, requests: 1Ti, maxClaims: 10}
  mesh: {enabled: false}
```

`kubectl get tenants` shows owners, CPU, GPUs, mesh and reconcile phase.

## Repository layout

| Path | What it is |
|---|---|
| `operator/tenant_operator/resources.py` | Pure functions: spec validation and object builders (unit-tested) |
| `operator/tenant_operator/handlers.py` | kopf handlers: create/update/resume, drift timer, delete, probes |
| `operator/tenant_operator/metrics.py` | Prometheus counters, histogram and gauge on `:8080/metrics` |
| `deploy/` | CRD, least-privilege RBAC, hardened Deployment, kustomization |
| `deploy/monitoring/` | ServiceMonitor and PrometheusRule (needs Prometheus Operator CRDs) |
| `puppet/modules/k8s_node/` | Puppet module that prepares Debian/Ubuntu bare-metal nodes |
| `.gitlab-ci.yml` | lint → unit tests → kaniko image build → kind e2e (docker-in-docker) |
| `.github/workflows/ci.yml` | Same pipeline on GitHub Actions |
| `hack/e2e.sh` | End-to-end test on a 3-node kind cluster |
| `docs/runbook.md` | One section per alert |

## Run it

```bash
make test        # unit tests, no cluster needed
make e2e         # kind cluster, build + load image, deploy, assert, tear down (needs docker, kind, kubectl)
make run         # run the operator from your laptop against the current kube context
```

Puppet on a test VM:

```bash
sudo puppet apply --modulepath=puppet/modules puppet/examples/site.pp
```

## Security design

An operator that creates namespaces and RoleBindings is powerful, so it is fenced in on four layers:

| Layer | Control |
|---|---|
| API schema (CRD) | Patterns for every quantity and name, unique storage classes, CEL rule rejecting `kube-*`, `default`, `monitoring` and other platform names |
| Operator code | Refuses to adopt a namespace it did not create, so deleting a Tenant can never garbage-collect someone else's namespace |
| Admission (`deploy/admission-policy.yaml`) | ValidatingAdmissionPolicy: the operator's identity may only write into namespaces it manages and may only bind the `edit` ClusterRole, even though its RBAC is cluster-wide |
| Runtime | Non-root UID/GID 10001, read-only root filesystem, all capabilities dropped, seccomp `RuntimeDefault`, Pod Security `restricted`, ingress limited to Prometheus |

Supply chain: multi-stage image on a digest-pinned base, code owned by root inside the image,
Trivy dependency and misconfiguration scans in CI (accepted findings documented in `.trivyignore`),
Dependabot for pip, Docker and Actions, and a read-only workflow token.

The e2e test checks the security behaviour too: a `kube-system` Tenant is rejected, an existing namespace is not adopted,
and the operator identity is blocked from writing into `default`.

## Design notes and limits

- **Single replica.** kopf runs one active reconciler; for HA, run two replicas with kopf peering enabled
  (drop `--standalone` and install the peering CRDs) so only one is active.
- **Mesh + restricted Pod Security.** Istio's init container needs `NET_ADMIN`, which the `restricted` profile forbids.
  Mesh-enabled tenants need the Istio CNI plugin on the nodes.
- **GPU quota** limits `requests.nvidia.com/gpu`; scheduling GPUs still needs the NVIDIA device plugin, and the Puppet
  module only switches containerd to the NVIDIA runtime when `enable_gpu => true`.
- **Drift check** re-applies every object every five minutes; server-side apply makes that a no-op when nothing changed.
- **Not covered:** cluster bootstrap (kubeadm), storage backends (e.g. Ceph/Rook), multi-cluster. These are the next steps.
