#!/usr/bin/env python3
"""Render a one-page PNG that demonstrates the lab.

Every decision on the board is produced by running the real policy engine
against `config/policies.json`, so the picture cannot drift from the code.

    python3 scripts/render_demo_image.py
    python3 scripts/render_demo_image.py --output docs/demo.png --dark
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.patheffects as path_effects  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

from dashboard import tokens  # noqa: E402
from demo.scenarios import scenarios_by_stage  # noqa: E402
from dns_manager.policy import PolicyEngine  # noqa: E402

# The queries the board explains, in the order a demo tells them.
# (agent, domain, note, queries) - the last decision of the burst is shown, so
# the throttled row is genuinely throttled rather than captioned as such.
STORY = [
    ("researcher", "docs.internal", "reads internal docs", 1),
    ("researcher", "pypi.org", "installs from the mirror", 1),
    ("deployer", "api.internal", "reaches the deploy API", 1),
    ("deployer", "metadata.internal", "SSRF via a wildcard grant", 1),
    ("researcher", "5ca1ab1e" * 6 + ".pypi.org", "DNS tunnelling attempt", 1),
    ("researcher", "pypi.org.evil.example", "lookalike registry", 1),
    ("untrusted", "docs.internal", "no allowlist at all", 1),
    ("load-tester", "docs.internal", "4th query in one second", 4),
    ("deployer", "api.anthropic.com", "6th metered call this minute", 6),
]

PIPELINE = [
    ("identity", "source address → agent"),
    ("deny rules", "global, then per-agent"),
    ("query guard", "label length · depth · size"),
    ("allowlist", "exact + anchored wildcard"),
    ("quota + budget", "queries/second · rolling cost"),
    ("health", "drop failed endpoints"),
    ("balance", "round-robin the rest"),
]


class Palette:
    def __init__(self, dark: bool):
        self.dark = dark
        self.page = "#0d0d0d" if dark else "#f9f9f7"
        self.surface = "#1a1a19" if dark else "#ffffff"
        self.sunk = "#131312" if dark else "#f1f0ea"
        self.ink = "#ffffff" if dark else "#0b0b0b"
        self.ink_soft = "#c3c2b7" if dark else "#52514e"
        self.muted = "#898781"
        self.line = "#2c2c2a" if dark else "#e1e0d9"


ACTION_STYLE = {
    "ALLOW": (tokens.GOOD, "ALLOW"),
    "THROTTLE": (tokens.WARNING, "THROTTLE"),
    "BLOCK": (tokens.CRITICAL, "BLOCK"),
    "SERVFAIL": (tokens.SERIOUS, "SERVFAIL"),
    "NXDOMAIN": (tokens.SERIOUS, "NXDOMAIN"),
}


def card(ax, x, y, w, h, palette, face=None, edge=None, lw=1.0, radius=0.012):
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle=f"round,pad=0,rounding_size={radius}",
            facecolor=face or palette.surface,
            edgecolor=edge or palette.line,
            linewidth=lw,
            zorder=2,
        )
    )


def text(ax, x, y, label, palette, size=9, color=None, weight="normal", ha="left", va="center", family=None):
    return ax.text(
        x, y, label,
        fontsize=size,
        color=color or palette.ink,
        fontweight=weight,
        ha=ha, va=va,
        family=family or "DejaVu Sans",
        zorder=4,
    )


def chip(ax, x, y, label, color, palette, size=7.5):
    """A coloured dot plus its word: status is never carried by hue alone."""
    ax.plot([x], [y], marker="o", markersize=5, color=color, zorder=5)
    text(ax, x + 0.011, y, label, palette, size=size, color=palette.ink_soft, weight="bold")


def truncate(value: str, limit: int = 34) -> str:
    return value if len(value) <= limit else value[: limit - 1] + "…"


def render(engine: PolicyEngine, output: Path, dark: bool) -> Path:
    palette = Palette(dark)
    fig = plt.figure(figsize=(16, 9), dpi=140)
    fig.patch.set_facecolor(palette.page)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.set_facecolor(palette.page)

    # ---- header
    text(ax, 0.035, 0.945, "AgentDNS Sentinel", palette, size=27, weight="bold")
    text(
        ax, 0.035, 0.906,
        "Agent egress governance in one Runloop Devbox — every DNS answer is an identity decision, and every decision is evidence.",
        palette, size=10.5, color=palette.ink_soft,
    )
    card(ax, 0.788, 0.918, 0.177, 0.048, palette, face=palette.sunk, edge=palette.line)
    total = sum(len(items) for _, _, _, items in scenarios_by_stage())
    text(ax, 0.80, 0.942, f"{total} scenarios · {len(scenarios_by_stage())} acts",
         palette, size=9.5, weight="bold")
    text(ax, 0.80, 0.928, "each reports PASS / FAIL", palette, size=8, color=palette.muted)

    # ---- agents
    agents = engine.agents()
    text(ax, 0.035, 0.856, "AGENTS", palette, size=8.5, weight="bold", color=palette.muted)
    top, height, gap = 0.815, 0.062, 0.012
    for index, agent in enumerate(agents):
        y = top - index * (height + gap)
        card(ax, 0.035, y - height, 0.215, height, palette)
        ax.add_patch(
            FancyBboxPatch(
                (0.035, y - height), 0.004, height,
                boxstyle="round,pad=0,rounding_size=0.002",
                facecolor=tokens.ACT_COLORS[index % len(tokens.ACT_COLORS)],
                edgecolor="none", zorder=3,
            )
        )
        text(ax, 0.05, y - 0.019, agent["name"], palette, size=10.5, weight="bold")
        text(ax, 0.05, y - 0.034, agent["ip"], palette, size=8, color=palette.muted, family="DejaVu Sans Mono")
        allowed = ", ".join(agent["allowed_domains"]) or "no domains allowed"
        text(ax, 0.05, y - 0.049, truncate(allowed, 32), palette, size=7.5, color=palette.ink_soft)
        text(ax, 0.238, y - 0.034, f"{agent['requests_per_second']} q/s", palette,
             size=8, color=palette.muted, ha="right")

    # ---- policy pipeline
    text(ax, 0.30, 0.856, "POLICY PIPELINE", palette, size=8.5, weight="bold", color=palette.muted)
    card(ax, 0.30, 0.395, 0.185, 0.425, palette, face=palette.sunk)
    text(ax, 0.315, 0.795, "DNS manager", palette, size=11, weight="bold")
    text(ax, 0.315, 0.777, "172.28.0.53", palette, size=8, color=palette.muted, family="DejaVu Sans Mono")
    for index, (name, detail) in enumerate(PIPELINE):
        y = 0.745 - index * 0.048
        highlighted = name in {"deny rules", "query guard"}
        ax.plot([0.322], [y], marker="o", markersize=4.5,
                color=tokens.CRITICAL if highlighted else palette.muted, zorder=5)
        if index < len(PIPELINE) - 1:
            ax.plot([0.322, 0.322], [y - 0.008, y - 0.040], color=palette.line, lw=1.2, zorder=3)
        text(ax, 0.336, y + 0.006, name, palette, size=9.5, weight="bold")
        text(ax, 0.336, y - 0.010, detail, palette, size=7.5, color=palette.muted)
    text(ax, 0.315, 0.412, "deny and guard run before the allowlist", palette,
         size=7.5, color=tokens.CRITICAL, weight="bold")

    for y in (0.70, 0.60):
        ax.add_patch(FancyArrowPatch((0.256, y), (0.295, y), arrowstyle="-|>",
                                     mutation_scale=11, color=palette.muted, lw=1.1, zorder=3))

    # ---- services
    text(ax, 0.535, 0.856, "SERVICES", palette, size=8.5, weight="bold", color=palette.muted)
    seen, services = set(), []
    for endpoint in engine.endpoints():
        if endpoint["address"] not in seen:
            seen.add(endpoint["address"])
            services.append(endpoint)
    for index, endpoint in enumerate(services):
        y = 0.815 - index * 0.075
        card(ax, 0.535, y - 0.062, 0.185, 0.062, palette)
        text(ax, 0.549, y - 0.022, endpoint["address"], palette, size=10, weight="bold",
             family="DejaVu Sans Mono")
        chip(ax, 0.551, y - 0.044, "healthy · probe", tokens.GOOD, palette, size=7.5)
    ax.add_patch(FancyArrowPatch((0.492, 0.65), (0.53, 0.65), arrowstyle="-|>",
                                 mutation_scale=11, color=palette.muted, lw=1.1, zorder=3))
    text(ax, 0.535, 0.575, "Public names resolve to the lab's own", palette, size=7.5, color=palette.muted)
    text(ax, 0.535, 0.560, "stand-ins: split-horizon DNS, so nothing", palette, size=7.5, color=palette.muted)
    text(ax, 0.535, 0.545, "leaves the Devbox.", palette, size=7.5, color=palette.muted)

    # ---- live decisions, evaluated for real
    text(ax, 0.745, 0.856, "REAL DECISIONS FROM THIS POLICY", palette, size=8.5,
         weight="bold", color=palette.muted)
    card(ax, 0.745, 0.395, 0.222, 0.425, palette)
    lookup = {agent["name"]: agent["ip"] for agent in agents}
    for index, (agent, domain, note, queries) in enumerate(STORY):
        for _ in range(queries):
            decision = engine.evaluate(lookup[agent], domain)
        color, label = ACTION_STYLE.get(decision.action, (palette.muted, decision.action))
        y = 0.792 - index * 0.0448
        chip(ax, 0.760, y, label, color, palette, size=7.5)
        text(ax, 0.760, y - 0.015, f"{agent} → {truncate(domain, 30)}", palette,
             size=7.5, color=palette.ink, family="DejaVu Sans Mono")
        text(ax, 0.760, y - 0.029, f"{note} · {decision.reason}", palette, size=7,
             color=palette.muted)
        if index < len(STORY) - 1:
            ax.plot([0.755, 0.957], [y - 0.038, y - 0.038], color=palette.line, lw=0.7, zorder=3)

    # ---- the acts
    text(ax, 0.035, 0.335, "THE DEMONSTRATION, IN FIVE ACTS", palette, size=8.5,
         weight="bold", color=palette.muted)
    acts = scenarios_by_stage()
    width, gap = 0.176, 0.0125
    for index, (_, title, subtitle, scenarios) in enumerate(acts):
        x = 0.035 + index * (width + gap)
        color = tokens.ACT_COLORS[index % len(tokens.ACT_COLORS)]
        card(ax, x, 0.135, width, 0.18, palette)
        ax.add_patch(FancyBboxPatch((x, 0.307), width, 0.008,
                                    boxstyle="round,pad=0,rounding_size=0.002",
                                    facecolor=color, edgecolor="none", zorder=3))
        text(ax, x + 0.012, 0.288, f"{index + 1}. {title}", palette, size=11, weight="bold")
        text(ax, x + 0.012, 0.271, subtitle, palette, size=7.5, color=palette.muted)
        for row, scenario in enumerate(scenarios):
            y = 0.246 - row * 0.031
            ax.plot([x + 0.017], [y], marker="o", markersize=3.5, color=color, zorder=5)
            text(ax, x + 0.027, y + 0.004, scenario.id, palette, size=8,
                 weight="bold", family="DejaVu Sans Mono")
            text(ax, x + 0.027, y - 0.010, truncate(scenario.challenge, 30), palette,
                 size=6.8, color=palette.muted)

    # ---- footer
    ax.plot([0.035, 0.965], [0.062, 0.062], color=palette.line, lw=1)
    text(ax, 0.035, 0.040,
         "Runloop Network Policy is the non-bypassable outer egress boundary; this resolver is the fine-grained agent policy inside it.",
         palette, size=8, color=palette.muted)
    text(ax, 0.965, 0.040, "make demo-ready", palette, size=8.5, weight="bold",
         color=palette.ink_soft, ha="right").set_path_effects(
        [path_effects.Normal()]
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, facecolor=palette.page, dpi=140)
    plt.close(fig)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", default="docs/agentdns-sentinel-demo.png")
    parser.add_argument("--config", default=str(REPO_ROOT / "config" / "policies.json"))
    parser.add_argument("--dark", action="store_true", help="render on the dark surface")
    args = parser.parse_args()

    engine = PolicyEngine(args.config)
    path = render(engine, Path(args.output), args.dark)
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
