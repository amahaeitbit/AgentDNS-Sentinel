"""Compiled policy rules.

The resolver evaluates these on every DNS query, so the matching structures are
built once when the configuration is loaded rather than re-derived per lookup:
exact names land in a set, wildcards become anchored suffixes, and the agent
lookup is a dictionary keyed by source address.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Iterable, Tuple


def normalize_domain(domain: str) -> str:
    return domain.rstrip(".").lower()


def compile_patterns(patterns: Iterable[str]) -> Tuple[FrozenSet[str], Tuple[str, ...]]:
    """Split patterns into exact names and anchored wildcard suffixes.

    `*.pypi.org` becomes the suffix `.pypi.org`, which deliberately does **not**
    match the apex `pypi.org`, nor lookalikes such as `pypi.org.evil.example`
    or `notpypi.org`. Suffix matching is anchored on a label boundary.
    """
    exact: set[str] = set()
    suffixes: list[str] = []
    for pattern in patterns:
        pattern = normalize_domain(pattern)
        if not pattern:
            continue
        if pattern.startswith("*."):
            suffixes.append(pattern[1:])
        else:
            exact.add(pattern)
    return frozenset(exact), tuple(sorted(set(suffixes)))


def matches(domain: str, exact: FrozenSet[str], suffixes: Tuple[str, ...]) -> bool:
    if domain in exact:
        return True
    return any(domain.endswith(suffix) for suffix in suffixes)


@dataclass(frozen=True)
class QueryGuard:
    """Rejects query shapes that carry data rather than name a service.

    DNS tunnelling hides payload in long, numerous labels under a domain the
    agent is legitimately allowed to resolve, so an allowlist alone never
    catches it.
    """

    enabled: bool = True
    max_label_length: int = 40
    max_labels: int = 8
    max_length: int = 100

    @classmethod
    def from_config(cls, config: dict | None) -> "QueryGuard":
        config = config or {}
        return cls(
            enabled=bool(config.get("enabled", True)),
            max_label_length=int(config.get("max_label_length", 40)),
            max_labels=int(config.get("max_labels", 8)),
            max_length=int(config.get("max_length", 100)),
        )

    def violation(self, domain: str) -> str:
        """The reason this query looks like tunnelling, or "" if it looks normal."""
        if not self.enabled or not domain:
            return ""
        if len(domain) > self.max_length:
            return "query_name_too_long"
        labels = domain.split(".")
        if len(labels) > self.max_labels:
            return "too_many_labels"
        if any(len(label) > self.max_label_length for label in labels):
            return "label_too_long"
        return ""


@dataclass(frozen=True)
class CostTable:
    """What each destination costs to reach.

    Unlisted destinations are free, so a budget only ever constrains the
    metered services it was written for.
    """

    exact: Dict[str, float] = field(default_factory=dict)
    suffixes: Tuple[Tuple[str, float], ...] = ()

    @classmethod
    def build(cls, costs: dict | None) -> "CostTable":
        exact: Dict[str, float] = {}
        suffixes: list[tuple[str, float]] = []
        for pattern, cost in (costs or {}).items():
            pattern = normalize_domain(pattern)
            if pattern.startswith("*."):
                suffixes.append((pattern[1:], float(cost)))
            elif pattern:
                exact[pattern] = float(cost)
        # Longest suffix first, so a specific rule beats a broad one.
        suffixes.sort(key=lambda item: len(item[0]), reverse=True)
        return cls(exact=exact, suffixes=tuple(suffixes))

    def cost_of(self, domain: str) -> float:
        if domain in self.exact:
            return self.exact[domain]
        for suffix, cost in self.suffixes:
            if domain.endswith(suffix):
                return cost
        return 0.0


@dataclass(frozen=True)
class AgentRules:
    name: str
    ip: str
    limit: int
    allowed_domains: Tuple[str, ...]
    denied_domains: Tuple[str, ...]
    budget: object = None
    allow_exact: FrozenSet[str] = frozenset()
    allow_suffix: Tuple[str, ...] = ()
    deny_exact: FrozenSet[str] = frozenset()
    deny_suffix: Tuple[str, ...] = ()

    @classmethod
    def build(cls, name: str, policy: dict) -> "AgentRules":
        allowed = tuple(policy.get("allowed_domains", []) or ())
        denied = tuple(policy.get("denied_domains", []) or ())
        allow_exact, allow_suffix = compile_patterns(allowed)
        deny_exact, deny_suffix = compile_patterns(denied)
        from .budget import Budget

        return cls(
            name=name,
            ip=policy.get("ip", ""),
            limit=max(int(policy.get("requests_per_second", 1)), 1),
            budget=Budget.from_config(policy.get("budget")),
            allowed_domains=allowed,
            denied_domains=denied,
            allow_exact=allow_exact,
            allow_suffix=allow_suffix,
            deny_exact=deny_exact,
            deny_suffix=deny_suffix,
        )

    def allows(self, domain: str) -> bool:
        return matches(domain, self.allow_exact, self.allow_suffix)

    def denies(self, domain: str) -> bool:
        return matches(domain, self.deny_exact, self.deny_suffix)


@dataclass(frozen=True)
class CompiledPolicy:
    """An immutable snapshot the resolver can read without taking a lock."""

    agents_by_ip: Dict[str, AgentRules] = field(default_factory=dict)
    agents_by_name: Dict[str, AgentRules] = field(default_factory=dict)
    records: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    costs: CostTable = field(default_factory=CostTable)
    deny_exact: FrozenSet[str] = frozenset()
    deny_suffix: Tuple[str, ...] = ()
    denied_domains: Tuple[str, ...] = ()
    guard: QueryGuard = QueryGuard()
    ttl: int = 2

    @classmethod
    def build(cls, config: dict) -> "CompiledPolicy":
        agents = {
            name: AgentRules.build(name, policy)
            for name, policy in (config.get("agents") or {}).items()
        }
        denied = tuple(config.get("denied_domains", []) or ())
        deny_exact, deny_suffix = compile_patterns(denied)
        return cls(
            agents_by_ip={rules.ip: rules for rules in agents.values() if rules.ip},
            agents_by_name=agents,
            records={
                normalize_domain(domain): tuple(addresses)
                for domain, addresses in (config.get("records") or {}).items()
            },
            deny_exact=deny_exact,
            deny_suffix=deny_suffix,
            denied_domains=denied,
            costs=CostTable.build(config.get("costs")),
            guard=QueryGuard.from_config(config.get("query_guard")),
            ttl=int(config.get("ttl_seconds", 2)),
        )

    def denies(self, domain: str) -> bool:
        return matches(domain, self.deny_exact, self.deny_suffix)
