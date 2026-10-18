.PHONY: test lint run e2e e2e-keep

test:
	cd operator && python -m pytest -q

lint:
	ruff check operator/ && ruff format --check operator/
	puppet parser validate puppet/modules/k8s_node/manifests/*.pp
	puppet-lint --fail-on-warnings --no-documentation-check puppet/modules

# Run the operator from your laptop against the current kubeconfig context.
run:
	kubectl apply -f deploy/crd.yaml
	cd operator && PYTHONPATH=. kopf run --standalone --all-namespaces -m tenant_operator.handlers

e2e:
	bash hack/e2e.sh

e2e-keep:
	bash hack/e2e.sh --keep
