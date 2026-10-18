#!/usr/bin/env bash
# End-to-end test on a throwaway kind cluster.
# Needs: docker, kind, kubectl.  Usage: hack/e2e.sh [--keep]
set -euo pipefail

CLUSTER=tenant-e2e
IMAGE=tenant-operator:dev
KEEP=${1:-}
cd "$(dirname "$0")/.."

cleanup() {
  if [[ "$KEEP" != "--keep" ]]; then
    kind delete cluster --name "$CLUSTER" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

fail() { echo "FAIL: $*" >&2; kubectl -n tenant-operator logs deploy/tenant-operator --tail=50 || true; exit 1; }

echo "==> creating kind cluster"
kind create cluster --name "$CLUSTER" --config hack/kind-config.yaml --wait 120s

echo "==> building and loading operator image"
docker build -t "$IMAGE" operator/
kind load docker-image "$IMAGE" --name "$CLUSTER"

echo "==> deploying operator"
kubectl apply -f deploy/crd.yaml
kubectl wait --for=condition=Established crd/tenants.platform.example.io --timeout=60s
kubectl apply -k deploy/
kubectl -n tenant-operator rollout status deploy/tenant-operator --timeout=120s

echo "==> creating tenant team-ml"
kubectl apply -f examples/tenant-team-ml.yaml

for _ in $(seq 1 30); do
  kubectl get resourcequota tenant-quota -n team-ml >/dev/null 2>&1 && break
  sleep 2
done

gpu=$(kubectl get resourcequota tenant-quota -n team-ml -o jsonpath='{.spec.hard.requests\.nvidia\.com/gpu}') \
  || fail "quota not created"
[[ "$gpu" == "4" ]] || fail "expected 4 GPUs in quota, got '$gpu'"

for np in default-deny-ingress allow-same-namespace allow-prometheus-scrape; do
  kubectl get networkpolicy "$np" -n team-ml >/dev/null || fail "networkpolicy $np missing"
done
kubectl get rolebinding tenant-owners -n team-ml >/dev/null || fail "owner rolebinding missing"

echo "==> drift: deleting the quota by hand, operator must restore it on its next drift check"
echo "    (skipped by default because the drift interval is 5 minutes; run with DRIFT=1 to include)"
if [[ "${DRIFT:-0}" == "1" ]]; then
  kubectl delete resourcequota tenant-quota -n team-ml
  for _ in $(seq 1 40); do
    kubectl get resourcequota tenant-quota -n team-ml >/dev/null 2>&1 && break
    sleep 10
  done
  kubectl get resourcequota tenant-quota -n team-ml >/dev/null || fail "drift was not corrected"
fi

echo "==> invalid spec is rejected (API schema) and the operator keeps running"
kubectl apply -f - <<'EOF' || true
apiVersion: platform.example.io/v1alpha1
kind: Tenant
metadata:
  name: bad-quota
spec:
  ownersGroup: nobody
  quota:
    cpu: lots
EOF
sleep 5
kubectl get ns bad-quota >/dev/null 2>&1 && fail "namespace created for invalid tenant"
kubectl -n tenant-operator get pod -l app.kubernetes.io/name=tenant-operator \
  -o jsonpath='{.items[0].status.containerStatuses[0].restartCount}' | grep -qx 0 \
  || fail "operator restarted"

echo "==> security: reserved names are rejected by the API server"
if kubectl apply -f - >/dev/null 2>&1 <<'EOF'
apiVersion: platform.example.io/v1alpha1
kind: Tenant
metadata:
  name: kube-system
spec:
  ownersGroup: attacker
EOF
then fail "Tenant named kube-system was accepted"; fi

echo "==> security: an existing namespace is never adopted"
kubectl create namespace legacy-team
kubectl apply -f - <<'EOF'
apiVersion: platform.example.io/v1alpha1
kind: Tenant
metadata:
  name: legacy-team
spec:
  ownersGroup: someone
EOF
sleep 8
kubectl get resourcequota tenant-quota -n legacy-team >/dev/null 2>&1 && fail "operator adopted an existing namespace"
kubectl get ns legacy-team -o jsonpath='{.metadata.ownerReferences}' | grep -q Tenant \
  && fail "existing namespace got an owner reference"
kubectl delete tenant legacy-team --wait=true --timeout=60s
kubectl get ns legacy-team >/dev/null || fail "deleting the Tenant removed a namespace it never owned"

echo "==> security: admission policy blocks the operator identity outside its namespaces"
OP_SA=system:serviceaccount:tenant-operator:tenant-operator
if kubectl --as="$OP_SA" create quota sneaky --hard=pods=1 -n default >/dev/null 2>&1; then
  fail "operator identity could write a quota into the default namespace"
fi

echo "==> deleting tenant garbage-collects its namespace"
kubectl delete tenant team-ml --wait=true --timeout=60s
kubectl wait --for=delete ns/team-ml --timeout=120s || fail "namespace not garbage-collected"

echo "PASS"
