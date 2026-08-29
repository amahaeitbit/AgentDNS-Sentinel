import json
import tempfile
import unittest
from pathlib import Path

from dns_manager.policy import PolicyEngine
from dns_manager.rules import CompiledPolicy, QueryGuard, compile_patterns, matches

CONFIG = {
    "agents": {
        # A deliberately over-broad allowlist, as often written in practice.
        "deployer": {
            "ip": "10.0.0.12",
            "allowed_domains": ["*.internal", "registry.npmjs.org"],
            "requests_per_second": 100,
        },
        "researcher": {
            "ip": "10.0.0.11",
            "allowed_domains": ["pypi.org", "*.pypi.org"],
            "denied_domains": ["mirror.pypi.org"],
            "requests_per_second": 100,
        },
    },
    "denied_domains": ["metadata.internal", "*.admin.internal"],
    "query_guard": {"max_label_length": 20, "max_labels": 5, "max_length": 60},
    "records": {
        "api.internal": ["10.0.0.22"],
        "metadata.internal": ["169.254.169.254"],
        "pypi.org": ["10.0.0.21"],
        "files.pypi.org": ["10.0.0.21"],
        "mirror.pypi.org": ["10.0.0.21"],
        "registry.npmjs.org": ["10.0.0.21"],
    },
    "ttl_seconds": 2,
}


class PatternMatchingTest(unittest.TestCase):
    def test_wildcards_are_anchored_on_a_label_boundary(self):
        exact, suffixes = compile_patterns(["pypi.org", "*.pypi.org"])
        self.assertTrue(matches("pypi.org", exact, suffixes))
        self.assertTrue(matches("files.pypi.org", exact, suffixes))
        for lookalike in ("pypi.org.evil.example", "notpypi.org", "evilpypi.org"):
            self.assertFalse(matches(lookalike, exact, suffixes), lookalike)

    def test_a_bare_wildcard_does_not_cover_its_own_apex(self):
        exact, suffixes = compile_patterns(["*.pypi.org"])
        self.assertFalse(matches("pypi.org", exact, suffixes))
        self.assertTrue(matches("a.pypi.org", exact, suffixes))

    def test_patterns_are_normalised(self):
        exact, suffixes = compile_patterns(["PyPI.ORG.", "*.Example.COM", "", "  "])
        self.assertIn("pypi.org", exact)
        self.assertEqual(suffixes, (".example.com",))


class QueryGuardTest(unittest.TestCase):
    def setUp(self):
        self.guard = QueryGuard(max_label_length=20, max_labels=5, max_length=60)

    def test_ordinary_names_pass(self):
        for domain in ("pypi.org", "files.pythonhosted.org", "api.internal"):
            self.assertEqual(self.guard.violation(domain), "", domain)

    def test_a_payload_bearing_label_is_caught(self):
        self.assertEqual(self.guard.violation("a" * 21 + ".pypi.org"), "label_too_long")

    def test_a_deeply_nested_name_is_caught(self):
        self.assertEqual(self.guard.violation("a.b.c.d.e.f.pypi.org"), "too_many_labels")

    def test_an_overlong_name_is_caught(self):
        # 62 characters in 3 labels: every label is legal, the whole name is not.
        domain = ".".join(["a" * 20] * 3)
        self.assertEqual(len(domain), 62)
        self.assertEqual(self.guard.violation(domain), "query_name_too_long")

    def test_the_guard_can_be_switched_off(self):
        off = QueryGuard(enabled=False, max_label_length=5)
        self.assertEqual(off.violation("a" * 40 + ".pypi.org"), "")

    def test_defaults_come_from_config(self):
        guard = QueryGuard.from_config({"max_labels": 3})
        self.assertEqual(guard.max_labels, 3)
        self.assertEqual(guard.max_label_length, 40)


class CompiledPolicyTest(unittest.TestCase):
    def test_agents_are_indexed_by_source_address(self):
        policy = CompiledPolicy.build(CONFIG)
        self.assertEqual(policy.agents_by_ip["10.0.0.12"].name, "deployer")
        self.assertIsNone(policy.agents_by_ip.get("10.0.0.99"))

    def test_record_domains_are_normalised(self):
        policy = CompiledPolicy.build({"records": {"API.Internal.": ["10.0.0.22"]}})
        self.assertEqual(policy.records["api.internal"], ("10.0.0.22",))

    def test_an_empty_config_compiles(self):
        policy = CompiledPolicy.build({})
        self.assertEqual(policy.agents_by_ip, {})
        self.assertFalse(policy.denies("anything.internal"))


class RealWorldPolicyTest(unittest.TestCase):
    """The behaviour the Defend act demonstrates, at the engine level."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        config = Path(self.tempdir.name) / "policies.json"
        config.write_text(json.dumps(CONFIG))
        self.engine = PolicyEngine(str(config))

    def tearDown(self):
        self.tempdir.cleanup()

    def test_a_deny_rule_beats_an_over_broad_allowlist(self):
        # `*.internal` covers it, and there is a real record behind it.
        allowed = self.engine.evaluate("10.0.0.12", "api.internal")
        self.assertEqual(allowed.action, "ALLOW")

        denied = self.engine.evaluate("10.0.0.12", "metadata.internal")
        self.assertEqual(denied.action, "BLOCK")
        self.assertEqual(denied.reason, "domain_denied")

    def test_a_wildcard_deny_rule_covers_subdomains(self):
        decision = self.engine.evaluate("10.0.0.12", "console.admin.internal")
        self.assertEqual(decision.reason, "domain_denied")

    def test_an_agent_can_carry_its_own_deny_rule(self):
        decision = self.engine.evaluate("10.0.0.11", "mirror.pypi.org")
        self.assertEqual(decision.action, "BLOCK")
        self.assertEqual(decision.reason, "domain_denied_for_agent")
        # The same name is fine for an agent without that rule in place.
        self.assertEqual(
            self.engine.evaluate("10.0.0.11", "files.pypi.org").action, "ALLOW"
        )

    def test_tunnelling_is_refused_under_an_allowed_domain(self):
        decision = self.engine.evaluate("10.0.0.11", "a" * 30 + ".pypi.org")
        self.assertEqual(decision.action, "BLOCK")
        self.assertEqual(decision.reason, "label_too_long")
        # The domain itself is genuinely allowed.
        self.assertEqual(self.engine.evaluate("10.0.0.11", "pypi.org").action, "ALLOW")

    def test_lookalike_domains_are_refused(self):
        for lookalike in ("pypi.org.evil.example", "notpypi.org"):
            decision = self.engine.evaluate("10.0.0.11", lookalike)
            self.assertEqual(decision.reason, "domain_not_allowed", lookalike)

    def test_deny_rules_are_checked_before_the_quota_is_spent(self):
        # A denied name must not let an agent exhaust its own rate limit.
        for _ in range(50):
            self.engine.evaluate("10.0.0.12", "metadata.internal")
        self.assertEqual(self.engine.evaluate("10.0.0.12", "api.internal").action, "ALLOW")

    def test_a_live_grant_takes_effect_immediately(self):
        self.assertEqual(
            self.engine.evaluate("10.0.0.11", "registry.npmjs.org").reason,
            "domain_not_allowed",
        )
        self.engine.set_domain_access("researcher", "registry.npmjs.org", True)
        self.assertEqual(
            self.engine.evaluate("10.0.0.11", "registry.npmjs.org").action, "ALLOW"
        )
        self.engine.set_domain_access("researcher", "registry.npmjs.org", False)
        self.assertEqual(
            self.engine.evaluate("10.0.0.11", "registry.npmjs.org").reason,
            "domain_not_allowed",
        )

    def test_a_grant_can_never_override_a_deny_rule(self):
        self.engine.set_domain_access("deployer", "metadata.internal", True)
        decision = self.engine.evaluate("10.0.0.12", "metadata.internal")
        self.assertEqual(decision.reason, "domain_denied")


class ShippedPolicyTest(unittest.TestCase):
    """Guards against the shipped configuration drifting away from the demo."""

    def setUp(self):
        config = Path(__file__).parents[1] / "config" / "policies.json"
        self.engine = PolicyEngine(str(config))

    def test_no_agent_can_reach_cloud_metadata(self):
        for agent in self.engine.agents():
            decision = self.engine.evaluate(agent["ip"], "metadata.internal")
            self.assertEqual(decision.action, "BLOCK", agent["name"])

    def test_the_deploy_agent_keeps_the_over_broad_wildcard_the_demo_relies_on(self):
        deployer = next(a for a in self.engine.agents() if a["name"] == "deployer")
        self.assertTrue(any(d.startswith("*.") for d in deployer["allowed_domains"]))

    def test_the_package_mirror_resolves_for_the_research_agent(self):
        self.assertEqual(
            self.engine.evaluate("172.28.0.11", "pypi.org").action, "ALLOW"
        )


if __name__ == "__main__":
    unittest.main()
