"""Unit tests for the pure resource builders. Run with: python -m pytest (or python -m unittest)."""

import unittest

from tenant_operator.resources import (
    TenantSpecError,
    build_all,
    namespace,
    namespace_is_ours,
    network_policies,
    parse_spec,
    resource_quota,
)

BASE = {"ownersGroup": "team-mail", "quota": {"cpu": "8", "memory": "32Gi"}}


class ParseSpecTests(unittest.TestCase):
    def test_defaults(self):
        t = parse_spec("team-mail", {"ownersGroup": "team-mail"})
        self.assertEqual((t.cpu, t.memory, t.gpus, t.mesh_enabled), ("4", "16Gi", 0, False))

    def test_rejects_invalid_name(self):
        for bad in ("Team_Mail", "-mail", "a" * 64, ""):
            with self.subTest(name=bad), self.assertRaises(TenantSpecError):
                parse_spec(bad, BASE)

    def test_rejects_reserved_names(self):
        for reserved in ("kube-system", "kube-anything", "default", "tenant-operator", "monitoring"):
            with self.subTest(name=reserved), self.assertRaises(TenantSpecError):
                parse_spec(reserved, BASE)

    def test_requires_owners_group(self):
        with self.assertRaises(TenantSpecError):
            parse_spec("team-mail", {"quota": {"cpu": "1"}})

    def test_rejects_bad_quantities(self):
        for quota in ({"cpu": "lots"}, {"memory": "16GB"}, {"gpus": -1}, {"gpus": True}, {"gpus": "2"}):
            with self.subTest(quota=quota), self.assertRaises(TenantSpecError):
                parse_spec("team-mail", {"ownersGroup": "g", "quota": quota})

    def test_rejects_duplicate_storage_class(self):
        spec = {
            "ownersGroup": "g",
            "storage": [
                {"storageClass": "ceph-rbd", "requests": "100Gi"},
                {"storageClass": "ceph-rbd", "requests": "50Gi"},
            ],
        }
        with self.assertRaises(TenantSpecError):
            parse_spec("team-mail", spec)


class OwnershipTests(unittest.TestCase):
    def test_only_namespaces_we_created_are_ours(self):
        ours = {"app.kubernetes.io/managed-by": "tenant-operator", "platform.example.io/tenant": "team-mail"}
        self.assertTrue(namespace_is_ours(ours, "team-mail"))
        self.assertFalse(namespace_is_ours(ours, "team-ml"))
        self.assertFalse(namespace_is_ours({"team": "mail"}, "team-mail"))
        self.assertFalse(namespace_is_ours(None, "team-mail"))


class BuilderTests(unittest.TestCase):
    def test_quota_includes_gpu_and_per_class_storage(self):
        spec = {
            **BASE,
            "quota": {**BASE["quota"], "gpus": 2},
            "storage": [
                {"storageClass": "ceph-rbd", "requests": "500Gi", "maxClaims": 20},
                {"storageClass": "local-nvme", "requests": "1Ti", "maxClaims": 5},
            ],
        }
        hard = resource_quota(parse_spec("team-ml", spec))["spec"]["hard"]
        self.assertEqual(hard["requests.nvidia.com/gpu"], "2")
        self.assertEqual(hard["ceph-rbd.storageclass.storage.k8s.io/requests.storage"], "500Gi")
        self.assertEqual(hard["local-nvme.storageclass.storage.k8s.io/persistentvolumeclaims"], "5")
        self.assertEqual(hard["persistentvolumeclaims"], "25")

    def test_no_storage_means_no_pvcs(self):
        hard = resource_quota(parse_spec("team-mail", BASE))["spec"]["hard"]
        self.assertEqual(hard["persistentvolumeclaims"], "0")

    def test_mesh_toggles_istio_injection(self):
        off = namespace(parse_spec("team-mail", BASE))
        on = namespace(parse_spec("team-mail", {**BASE, "mesh": {"enabled": True}}))
        self.assertEqual(off["metadata"]["labels"]["istio-injection"], "disabled")
        self.assertEqual(on["metadata"]["labels"]["istio-injection"], "enabled")

    def test_namespace_enforces_restricted_pod_security(self):
        labels = namespace(parse_spec("team-mail", BASE))["metadata"]["labels"]
        self.assertEqual(labels["pod-security.kubernetes.io/enforce"], "restricted")

    def test_default_deny_plus_scrape_allowance(self):
        names = [p["metadata"]["name"] for p in network_policies(parse_spec("team-mail", BASE))]
        self.assertEqual(names, ["default-deny-ingress", "allow-same-namespace", "allow-prometheus-scrape"])

    def test_namespace_applied_first_and_all_objects_namespaced_to_tenant(self):
        objs = build_all(parse_spec("team-mail", BASE))
        self.assertEqual(objs[0]["kind"], "Namespace")
        for obj in objs[1:]:
            self.assertEqual(obj["metadata"]["namespace"], "team-mail", obj["kind"])
            self.assertEqual(obj["metadata"]["labels"]["app.kubernetes.io/managed-by"], "tenant-operator")


if __name__ == "__main__":
    unittest.main()
