"""The page's building blocks."""

from __future__ import annotations

import reflex as rx

from demo.scenarios import SCENARIOS, scenarios_by_stage

from . import theme
from .state import ACTION_FILTERS, DashboardState

SCENARIO_NUMBERS = {scenario.id: index for index, scenario in enumerate(SCENARIOS, start=1)}
STAGE_SECTIONS = scenarios_by_stage()


# Reflex resolves icon names at build time, so a data-driven icon has to be a
# match over the known set rather than a name looked up in the data.
def action_icon(action, size: int = 14, color=None):
    def glyph(name):
        return rx.icon(name, size=size, color=color)

    return rx.match(
        action,
        ("ALLOW", glyph("circle-check")),
        ("THROTTLE", glyph("gauge")),
        ("BLOCK", glyph("shield-ban")),
        ("FAILURE", glyph("triangle-alert")),
        ("SERVFAIL", glyph("triangle-alert")),
        ("NXDOMAIN", glyph("search-x")),
        glyph("circle-dashed"),
    )


def health_icon(healthy, size: int = 13):
    return rx.cond(
        healthy,
        rx.icon("circle-check", size=size, color=theme.GOOD),
        rx.icon("triangle-alert", size=size, color=theme.CRITICAL),
    )


def verdict_icon(verdict, size: int = 13, color=None):
    def glyph(name):
        return rx.icon(name, size=size, color=color)

    return rx.match(
        verdict,
        ("PASS", glyph("circle-check")),
        ("FAIL", glyph("circle-x")),
        glyph("triangle-alert"),
    )


# ------------------------------------------------------------------ header


def connection_pill():
    return rx.cond(
        DashboardState.lab_online,
        rx.hstack(
            rx.box(width="7px", height="7px", border_radius="999px", background=theme.GOOD),
            rx.text("Lab online", size="1", color=theme.INK_SOFT, weight="medium"),
            rx.text(DashboardState.last_refresh, size="1", color=theme.INK_MUTED),
            spacing="2",
            align="center",
            padding="0.25rem 0.6rem",
            border_radius="999px",
            background=theme.SUNK,
        ),
        rx.hstack(
            rx.icon("triangle-alert", size=13, color=theme.CRITICAL),
            rx.text("Control API unreachable", size="1", color=theme.INK_SOFT),
            spacing="2",
            align="center",
            padding="0.25rem 0.6rem",
            border_radius="999px",
            background=theme.SUNK,
        ),
    )


def header():
    return rx.box(
        rx.hstack(
            rx.vstack(
                rx.hstack(
                    rx.badge("RUNLOOP DEVBOX", color_scheme="blue", variant="soft", size="1"),
                    connection_pill(),
                    spacing="2",
                    align="center",
                    wrap="wrap",
                ),
                rx.heading("AgentDNS Sentinel", size="7", color=theme.INK),
                rx.text(
                    "Reflex operator console for identity-aware DNS policy, per-agent "
                    "budgets, health-based failover, and auditable agent traffic.",
                    size="2",
                    color=theme.INK_MUTED,
                    max_width="60ch",
                ),
                align="start",
                spacing="2",
            ),
            rx.spacer(),
            rx.vstack(
                rx.hstack(
                    rx.button(
                        rx.icon("play", size=15),
                        "Run full demo",
                        on_click=DashboardState.run_all,
                        disabled=DashboardState.busy,
                        size="2",
                    ),
                    rx.button(
                        rx.icon("rotate-ccw", size=15),
                        "Reset",
                        on_click=DashboardState.reset_demo,
                        disabled=DashboardState.busy,
                        variant="soft",
                        size="2",
                    ),
                    rx.color_mode.button(),
                    spacing="2",
                    wrap="wrap",
                    justify="end",
                ),
                rx.hstack(
                    rx.switch(
                        checked=DashboardState.auto_refresh,
                        on_change=DashboardState.toggle_auto_refresh,
                        size="1",
                    ),
                    rx.text("Live updates", size="1", color=theme.INK_MUTED),
                    rx.text("·", size="1", color=theme.INK_MUTED),
                    rx.text(
                        f"{DashboardState.scoreboard} scenarios passing",
                        size="1",
                        color=theme.INK_SOFT,
                        weight="medium",
                    ),
                    spacing="2",
                    align="center",
                    justify="end",
                ),
                align="end",
                spacing="3",
            ),
            width="100%",
            align="start",
            wrap="wrap",
            spacing="4",
        ),
        position="sticky",
        top="0",
        z_index="10",
        background=theme.PAGE_BG,
        padding="1.25rem 0 1rem 0",
        border_bottom=rx.color_mode_cond(
            light="1px solid #e1e0d9", dark="1px solid #2c2c2a"
        ),
    )


# -------------------------------------------------------- operator workflow


def _workflow_step(icon: str, label: str, title: str, description: str):
    return rx.box(
        rx.vstack(
            rx.hstack(
                rx.center(
                    rx.icon(icon, size=16, color=theme.INK),
                    width="34px",
                    height="34px",
                    border_radius="10px",
                    background=theme.SUNK,
                ),
                rx.vstack(
                    rx.text(
                        label,
                        size="1",
                        weight="bold",
                        color=theme.INK_MUTED,
                        letter_spacing="0.08em",
                    ),
                    rx.heading(title, size="3", color=theme.INK),
                    spacing="0",
                    align="start",
                ),
                spacing="3",
                align="center",
            ),
            rx.text(description, size="2", color=theme.INK_SOFT),
            spacing="3",
            align="start",
        ),
        padding="0.85rem 0.95rem",
        border_radius="12px",
        background=theme.SUNK,
        width="100%",
        height="100%",
    )


def operator_workflow():
    """Explain the value Reflex adds without implying that it enforces traffic."""
    return theme.surface_card(
        rx.vstack(
            theme.section_heading(
                "What Reflex does",
                "One operator surface to observe, control, and prove agent-network behavior.",
                rx.badge("OPERATOR PLANE", color_scheme="blue", variant="soft"),
            ),
            rx.grid(
                _workflow_step(
                    "scan-eye",
                    "OBSERVE",
                    "See every decision",
                    "Follow agent identity, destination, outcome, quota, budget, and service health live.",
                ),
                _workflow_step(
                    "sliders-horizontal",
                    "CONTROL",
                    "Exercise the system",
                    "Run scenarios, inject a real endpoint failure, recover services, and reset the lab.",
                ),
                _workflow_step(
                    "file-check-2",
                    "PROVE",
                    "Keep the evidence",
                    "Review DNS decisions and attributed control changes, then export evidence through Runloop.",
                ),
                columns={"initial": "1", "md": "3"},
                spacing="3",
                width="100%",
            ),
            rx.flex(
                theme.status_pill(
                    "Reflex: visibility + controls",
                    rx.icon("layout-dashboard", size=13, color=theme.INK_SOFT),
                ),
                rx.icon("arrow-right", size=14, color=theme.INK_MUTED),
                theme.status_pill(
                    "AgentDNS: policy decisions",
                    rx.icon("waypoints", size=13, color=theme.INK_SOFT),
                ),
                rx.icon("arrow-right", size=14, color=theme.INK_MUTED),
                theme.status_pill(
                    "Runloop: isolation + boundary",
                    rx.icon("shield-check", size=13, color=theme.INK_SOFT),
                ),
                spacing="2",
                wrap="wrap",
                align="center",
            ),
            width="100%",
            spacing="4",
            align="start",
        )
    )


# ------------------------------------------------------------- stat tiles


def stat_tile(label: str, value, share, icon: str, color: str):
    return theme.surface_card(
        rx.vstack(
            rx.hstack(
                rx.icon(icon, size=15, color=color),
                rx.text(label, size="1", color=theme.INK_MUTED, weight="medium"),
                spacing="2",
                align="center",
            ),
            rx.heading(value, size="7", color=theme.INK),
            rx.text(share, size="1", color=theme.INK_MUTED),
            align="start",
            spacing="1",
        ),
        padding="1rem 1.1rem",
    )


def traffic_bar():
    """A single stacked bar: the share of decisions by outcome.

    Segments are separated by a 2px surface gap, direct-labelled when wide
    enough, and always repeated in the legend with an icon and a count.
    """
    return theme.surface_card(
        rx.vstack(
            theme.section_heading(
                "Decision mix",
                "Every DNS answer this lab has given, by outcome",
                rx.cond(
                    DashboardState.has_traffic,
                    rx.text(
                        f"{DashboardState.summary['total']} decisions",
                        size="1",
                        color=theme.INK_MUTED,
                    ),
                    rx.fragment(),
                ),
            ),
            rx.cond(
                DashboardState.has_traffic,
                rx.vstack(
                    rx.hstack(
                        rx.foreach(DashboardState.composition, _segment),
                        width="100%",
                        height="26px",
                        spacing="0",
                        gap="2px",
                    ),
                    rx.flex(
                        rx.foreach(DashboardState.composition, _legend_item),
                        wrap="wrap",
                        spacing="4",
                        width="100%",
                    ),
                    width="100%",
                    spacing="3",
                ),
                theme.empty_state(
                    "chart-no-axes-column",
                    "No decisions yet. Run an act below and the mix appears here.",
                ),
            ),
            width="100%",
            spacing="3",
            align="start",
        )
    )


def _segment(item):
    return rx.box(
        rx.cond(
            item["wide"],
            rx.center(
                rx.text(
                    item["count"],
                    size="1",
                    weight="bold",
                    color=item["on_fill"],
                ),
                height="100%",
            ),
            rx.fragment(),
        ),
        width=item["width"],
        height="100%",
        background=item["color"],
        border_radius="4px",
        min_width=item["min_width"],
        transition="width 400ms ease",
    )


def _legend_item(item):
    return rx.hstack(
        action_icon(item["action"], size=13, color=item["color"]),
        rx.text(item["label"], size="1", color=theme.INK_SOFT, weight="medium"),
        rx.text(item["count"], size="1", color=theme.INK, weight="bold"),
        rx.text(item["share"], size="1", color=theme.INK_MUTED),
        spacing="2",
        align="center",
    )


def stat_row():
    return rx.grid(
        stat_tile(
            "Decisions",
            DashboardState.summary["total"],
            "since the last reset",
            "activity",
            theme.INK_MUTED,
        ),
        stat_tile(
            "Allowed",
            DashboardState.summary["allowed"],
            "policy permitted",
            "circle-check",
            theme.GOOD,
        ),
        stat_tile(
            "Blocked",
            DashboardState.summary["blocked"],
            "domain not on the allowlist",
            "shield-ban",
            theme.CRITICAL,
        ),
        stat_tile(
            "Throttled",
            DashboardState.summary["throttled"],
            "over the per-agent quota",
            "gauge",
            theme.WARNING,
        ),
        columns={"initial": "2", "md": "4"},
        spacing="4",
        width="100%",
    )


# ---------------------------------------------------------------- topology


def _agent_node(agent):
    return rx.box(
        rx.hstack(
            rx.icon("bot", size=16, color=theme.INK_MUTED),
            rx.vstack(
                rx.text(agent["name"], size="2", weight="bold", color=theme.INK),
                rx.text(
                    agent["ip"],
                    size="1",
                    color=theme.INK_MUTED,
                    font_family="ui-monospace, monospace",
                ),
                spacing="0",
                align="start",
            ),
            rx.spacer(),
            theme.status_pill(
                agent["label"], action_icon(agent["action"], 13, agent["color"])
            ),
            width="100%",
            align="center",
            spacing="3",
        ),
        rx.hstack(
            rx.icon("shield", size=11, color=theme.INK_MUTED),
            rx.text(agent["domains"], size="1", color=theme.INK_MUTED),
            rx.text("·", size="1", color=theme.INK_MUTED),
            rx.text(agent["quota"], size="1", color=theme.INK_MUTED),
            spacing="1",
            align="center",
            margin_top="0.35rem",
            wrap="wrap",
        ),
        rx.text(
            agent["tally"],
            size="1",
            color=theme.INK_MUTED,
            margin_top="0.15rem",
        ),
        padding="0.6rem 0.75rem",
        border_radius="10px",
        background=theme.SURFACE,
        border=rx.color_mode_cond(light="1px solid #e1e0d9", dark="1px solid #2c2c2a"),
        border_left=f"3px solid {agent['color']}",
        width="100%",
    )


def _endpoint_node(endpoint):
    return rx.box(
        rx.hstack(
            rx.icon("server", size=16, color=theme.INK_MUTED),
            rx.vstack(
                rx.text(endpoint["domain"], size="2", weight="bold", color=theme.INK),
                rx.text(
                    endpoint["address"],
                    size="1",
                    color=theme.INK_MUTED,
                    font_family="ui-monospace, monospace",
                ),
                spacing="0",
                align="start",
            ),
            rx.spacer(),
            theme.status_pill(endpoint["label"], health_icon(endpoint["healthy"])),
            width="100%",
            align="center",
            spacing="3",
        ),
        rx.hstack(
            rx.text(endpoint["source"], size="1", color=theme.INK_MUTED),
            rx.spacer(),
            rx.button(
                rx.cond(
                    endpoint["healthy"],
                    rx.icon("power", size=12),
                    rx.icon("rotate-ccw", size=12),
                ),
                endpoint["action_label"],
                size="1",
                variant="soft",
                color_scheme=rx.cond(endpoint["healthy"], "gray", "green"),
                disabled=DashboardState.busy,
                on_click=DashboardState.set_endpoint_failure(
                    endpoint["address"], endpoint["fail"]
                ),
            ),
            width="100%",
            align="center",
            margin_top="0.4rem",
        ),
        padding="0.6rem 0.75rem",
        border_radius="10px",
        background=theme.SURFACE,
        border=rx.color_mode_cond(light="1px solid #e1e0d9", dark="1px solid #2c2c2a"),
        border_left=f"3px solid {endpoint['color']}",
        width="100%",
    )


def _rail(label: str):
    return rx.center(
        rx.vstack(
            rx.icon("chevron-right", size=20, color=theme.INK_MUTED),
            rx.text(
                label,
                size="1",
                color=theme.INK_MUTED,
                text_align="center",
                max_width="10ch",
            ),
            align="center",
            spacing="1",
        ),
        flex="0 0 auto",
        min_width="92px",
        padding="0.5rem 0",
    )


def _resolver_card():
    steps = [
        ("fingerprint", "Identity", "source IP → agent"),
        ("shield-ban", "Deny + guard", "block threats first"),
        ("shield", "Allowlist", "may it resolve this?"),
        ("gauge", "Quota + budget", "limit rate and cost"),
        ("heart-pulse", "Health + balance", "route to healthy replicas"),
    ]
    return rx.box(
        rx.vstack(
            rx.hstack(
                rx.icon("waypoints", size=18, color=theme.INK),
                rx.vstack(
                    rx.text("DNS manager", size="2", weight="bold", color=theme.INK),
                    rx.text(
                        "172.28.0.53",
                        size="1",
                        color=theme.INK_MUTED,
                        font_family="ui-monospace, monospace",
                    ),
                    spacing="0",
                    align="start",
                ),
                width="100%",
                align="center",
                spacing="2",
            ),
            rx.divider(),
            rx.vstack(
                *[
                    rx.hstack(
                        rx.icon(icon, size=13, color=theme.INK_MUTED),
                        rx.text(name, size="1", weight="medium", color=theme.INK_SOFT),
                        rx.text(detail, size="1", color=theme.INK_MUTED),
                        spacing="2",
                        align="center",
                        width="100%",
                    )
                    for icon, name, detail in steps
                ],
                spacing="2",
                width="100%",
                align="start",
            ),
            spacing="3",
            width="100%",
            align="start",
        ),
        padding="0.85rem 0.95rem",
        border_radius="12px",
        background=theme.SUNK,
        border=rx.color_mode_cond(light="1px solid #e1e0d9", dark="1px solid #2c2c2a"),
        width="100%",
    )


def topology():
    return theme.surface_card(
        rx.vstack(
            theme.section_heading(
                "Live topology",
                "Each agent's most recent decision, and the endpoints behind the answer",
                theme.status_pill(
                    DashboardState.healthy_summary,
                    health_icon(DashboardState.all_healthy, 13),
                ),
            ),
            rx.cond(
                DashboardState.lab_online,
                rx.flex(
                    rx.vstack(
                        rx.text(
                            "AGENTS",
                            size="1",
                            weight="bold",
                            color=theme.INK_MUTED,
                            letter_spacing="0.08em",
                        ),
                        rx.foreach(DashboardState.topology_agents, _agent_node),
                        spacing="2",
                        width="100%",
                        flex="1 1 300px",
                        align="start",
                    ),
                    _rail("ask"),
                    rx.vstack(
                        rx.text(
                            "POLICY",
                            size="1",
                            weight="bold",
                            color=theme.INK_MUTED,
                            letter_spacing="0.08em",
                        ),
                        _resolver_card(),
                        spacing="2",
                        width="100%",
                        flex="1 1 220px",
                        align="start",
                    ),
                    _rail("answer"),
                    rx.vstack(
                        rx.text(
                            "SERVICES",
                            size="1",
                            weight="bold",
                            color=theme.INK_MUTED,
                            letter_spacing="0.08em",
                        ),
                        rx.foreach(DashboardState.topology_endpoints, _endpoint_node),
                        spacing="2",
                        width="100%",
                        flex="1 1 280px",
                        align="start",
                    ),
                    width="100%",
                    align="start",
                    wrap="wrap",
                    spacing="3",
                ),
                theme.empty_state("plug", "Waiting for the DNS control API..."),
            ),
            width="100%",
            spacing="4",
            align="start",
        )
    )


# --------------------------------------------------------------- scenarios


def _verdict_badge(scenario_id: str):
    verdict = DashboardState.verdicts[scenario_id]
    return rx.cond(
        verdict,
        rx.hstack(
            verdict_icon(
                verdict,
                13,
                rx.match(verdict, ("PASS", theme.GOOD), ("FAIL", theme.CRITICAL), theme.SERIOUS),
            ),
            rx.text(verdict, size="1", weight="bold", color=theme.INK_SOFT),
            spacing="1",
            align="center",
        ),
        rx.fragment(),
    )


def scenario_card(scenario, accent: str):
    number = SCENARIO_NUMBERS[scenario.id]
    return rx.box(
        rx.vstack(
            rx.hstack(
                rx.text(
                    f"{number:02d}",
                    size="1",
                    weight="bold",
                    color=theme.INK_MUTED,
                    font_family="ui-monospace, monospace",
                ),
                rx.text(scenario.challenge, size="1", color=theme.INK_MUTED),
                rx.spacer(),
                _verdict_badge(scenario.id),
                rx.cond(
                    DashboardState.running_id == scenario.id,
                    rx.spinner(size="1"),
                    rx.fragment(),
                ),
                width="100%",
                align="center",
                spacing="2",
            ),
            rx.heading(scenario.title, size="3", color=theme.INK),
            rx.text(scenario.capability, size="2", color=theme.INK_SOFT),
            rx.text(scenario.watch_for, size="1", color=theme.INK_MUTED),
            rx.spacer(),
            rx.button(
                rx.icon("play", size=13),
                "Run",
                on_click=DashboardState.run_scenario(scenario.id),
                disabled=DashboardState.busy,
                variant="soft",
                size="1",
                width="100%",
            ),
            align="start",
            spacing="2",
            height="100%",
        ),
        padding="0.9rem 1rem",
        border_radius="12px",
        background=theme.SURFACE,
        border=rx.color_mode_cond(light="1px solid #e1e0d9", dark="1px solid #2c2c2a"),
        border_top=f"3px solid {accent}",
        height="100%",
    )


def act_section(act_index: int, key: str, title: str, subtitle: str, scenarios):
    accent = theme.ACT_COLORS[(act_index - 1) % len(theme.ACT_COLORS)]
    return rx.vstack(
        rx.hstack(
            rx.center(
                rx.text(str(act_index), size="2", weight="bold", color="#ffffff"),
                width="26px",
                height="26px",
                border_radius="8px",
                background=accent,
                flex_shrink="0",
            ),
            rx.vstack(
                rx.heading(title, size="4", color=theme.INK),
                rx.text(subtitle, size="1", color=theme.INK_MUTED),
                spacing="0",
                align="start",
            ),
            rx.spacer(),
            rx.text(
                DashboardState.acts[act_index - 1]["status"],
                size="1",
                color=theme.INK_MUTED,
            ),
            rx.button(
                "Run act",
                on_click=DashboardState.run_stage(key),
                disabled=DashboardState.busy,
                variant="outline",
                size="1",
            ),
            width="100%",
            align="center",
            spacing="3",
            wrap="wrap",
        ),
        rx.grid(
            *[scenario_card(scenario, accent) for scenario in scenarios],
            columns={"initial": "1", "md": "2", "xl": "3"},
            spacing="3",
            width="100%",
        ),
        spacing="3",
        width="100%",
        align="start",
    )


def scenarios_section():
    return rx.vstack(
        theme.section_heading(
            f"The demonstration, in {len(STAGE_SECTIONS)} acts",
            f"{len(SCENARIOS)} scenarios. Each one answers an operational challenge and reports pass or fail.",
        ),
        *[
            act_section(index, key, title, subtitle, scenarios)
            for index, (key, title, subtitle, scenarios) in enumerate(
                STAGE_SECTIONS, start=1
            )
        ],
        spacing="5",
        width="100%",
        align="start",
    )


# ------------------------------------------------------------ result panel


def _check_row(check):
    return rx.hstack(
        rx.cond(
            check["passed"],
            rx.icon("circle-check", size=15, color=theme.GOOD),
            rx.icon("circle-x", size=15, color=theme.CRITICAL),
        ),
        rx.text(check["label"], size="2", color=theme.INK_SOFT),
        rx.text(check["detail"], size="1", color=theme.INK_MUTED),
        spacing="2",
        align="center",
        wrap="wrap",
    )


def result_panel():
    return theme.surface_card(
        rx.vstack(
            rx.hstack(
                rx.heading("Latest result", size="4", color=theme.INK),
                rx.spacer(),
                rx.cond(
                    DashboardState.result_verdict != "",
                    rx.hstack(
                        verdict_icon(
                            DashboardState.result_verdict, 16, DashboardState.verdict_color
                        ),
                        rx.text(
                            DashboardState.result_verdict,
                            size="2",
                            weight="bold",
                            color=theme.INK,
                        ),
                        spacing="2",
                        align="center",
                    ),
                    rx.fragment(),
                ),
                width="100%",
                align="center",
            ),
            rx.text(DashboardState.message, size="2", color=theme.INK_SOFT),
            rx.cond(
                DashboardState.progress_total > 0,
                rx.vstack(
                    rx.progress(
                        value=DashboardState.progress_done,
                        max=DashboardState.progress_total,
                        width="100%",
                    ),
                    rx.text(
                        f"{DashboardState.progress_done} of {DashboardState.progress_total} scenarios",
                        size="1",
                        color=theme.INK_MUTED,
                    ),
                    spacing="1",
                    width="100%",
                ),
                rx.fragment(),
            ),
            rx.cond(
                DashboardState.result_title != "",
                rx.vstack(
                    rx.hstack(
                        rx.text(
                            DashboardState.result_stage,
                            size="1",
                            weight="bold",
                            color=theme.INK_MUTED,
                            letter_spacing="0.06em",
                        ),
                        rx.text("·", size="1", color=theme.INK_MUTED),
                        rx.text(DashboardState.result_challenge, size="1", color=theme.INK_MUTED),
                        spacing="2",
                        align="center",
                        wrap="wrap",
                    ),
                    rx.heading(DashboardState.result_title, size="3", color=theme.INK),
                    rx.text(DashboardState.result_headline, size="2", color=theme.INK_SOFT),
                    rx.vstack(
                        rx.foreach(DashboardState.result_checks, _check_row),
                        spacing="1",
                        width="100%",
                        align="start",
                    ),
                    spacing="2",
                    width="100%",
                    align="start",
                ),
                theme.empty_state("list-checks", "No scenario has run yet."),
            ),
            width="100%",
            spacing="3",
            align="start",
        )
    )


# ------------------------------------------------------------ decision log


def _filter_chip(action: str):
    active = DashboardState.action_filter == action
    return rx.button(
        action,
        size="1",
        variant=rx.cond(active, "solid", "soft"),
        color_scheme="gray",
        on_click=DashboardState.set_filter(action),
    )


def _event_row(event):
    color = rx.match(
        event["action"],
        ("ALLOW", theme.GOOD),
        ("THROTTLE", theme.WARNING),
        ("BLOCK", theme.CRITICAL),
        theme.SERIOUS,
    )
    return rx.table.row(
        rx.table.cell(
            rx.hstack(
                action_icon(event["action"], 14, color),
                rx.text(event["action"], size="1", weight="bold", color=theme.INK_SOFT),
                spacing="2",
                align="center",
            )
        ),
        rx.table.cell(rx.text(event["agent"], size="2", color=theme.INK)),
        rx.table.cell(
            rx.text(
                event["domain"],
                size="1",
                color=theme.INK_SOFT,
                font_family="ui-monospace, monospace",
            )
        ),
        rx.table.cell(
            rx.text(
                rx.cond(event["answer"], event["answer"], event["reason"]),
                size="1",
                color=theme.INK_MUTED,
                font_family="ui-monospace, monospace",
            )
        ),
        rx.table.cell(
            rx.text(
                event["source_ip"],
                size="1",
                color=theme.INK_MUTED,
                font_family="ui-monospace, monospace",
            )
        ),
        rx.table.cell(rx.text(rx.moment(event["created_at"], from_now=True), size="1", color=theme.INK_MUTED)),
    )


def _alert_row(row):
    return rx.hstack(
        rx.box(
            width="4px",
            border_radius="999px",
            background=row["color"],
            align_self="stretch",
            flex_shrink="0",
        ),
        rx.vstack(
            rx.hstack(
                rx.text(row["label"], size="1", weight="bold", color=row["color"]),
                rx.text(row["agent"], size="1", weight="bold", color=theme.INK),
                rx.text(row["usage"], size="1", color=theme.INK_MUTED),
                rx.text(row["percent"], size="1", color=theme.INK_MUTED),
                spacing="2",
                align="center",
                wrap="wrap",
            ),
            rx.text(row["message"], size="1", color=theme.INK_SOFT),
            spacing="1",
            align="start",
            width="100%",
        ),
        spacing="3",
        align="stretch",
        width="100%",
        padding="0.5rem 0",
    )


def _spend_row(row):
    return rx.vstack(
        rx.hstack(
            rx.text(row["agent"], size="1", weight="bold", color=theme.INK),
            rx.spacer(),
            rx.text(row["label"], size="1", color=theme.INK_MUTED),
            width="100%",
            align="center",
        ),
        rx.box(
            rx.box(
                width=row["width"],
                height="100%",
                background=row["color"],
                border_radius="999px",
            ),
            width="100%",
            height="6px",
            background=theme.SUNK,
            border_radius="999px",
            overflow="hidden",
        ),
        spacing="1",
        width="100%",
        align="start",
    )


def alerts_panel():
    """The notification surface: who is overspending, and by how much."""
    return theme.surface_card(
        rx.vstack(
            theme.section_heading(
                "Budget alerts",
                "Raised when an agent burns through its allowance for metered destinations",
                rx.cond(
                    DashboardState.alert_headline != "",
                    rx.hstack(
                        rx.icon("bell-ring", size=14, color=DashboardState.alert_color),
                        rx.text(
                            DashboardState.alert_headline,
                            size="1",
                            weight="bold",
                            color=theme.INK,
                        ),
                        spacing="2",
                        align="center",
                    ),
                    rx.fragment(),
                ),
            ),
            rx.cond(
                DashboardState.spend_rows.length() > 0,
                rx.vstack(
                    rx.foreach(DashboardState.spend_rows, _spend_row),
                    spacing="3",
                    width="100%",
                ),
                rx.fragment(),
            ),
            rx.cond(
                DashboardState.alert_rows.length() > 0,
                rx.vstack(
                    rx.divider(),
                    rx.foreach(DashboardState.alert_rows, _alert_row),
                    spacing="1",
                    width="100%",
                ),
                theme.empty_state(
                    "bell",
                    "No budget alerts. Run the Contain act to spend one.",
                ),
            ),
            width="100%",
            spacing="3",
            align="start",
        )
    )


def _audit_row(row):
    return rx.table.row(
        rx.table.cell(
            rx.hstack(
                rx.box(
                    width="6px",
                    height="6px",
                    border_radius="999px",
                    background=row["color"],
                    flex_shrink="0",
                ),
                rx.text(row["label"], size="1", weight="medium", color=theme.INK_SOFT),
                spacing="2",
                align="center",
            )
        ),
        rx.table.cell(
            rx.text(
                row["resource"],
                size="1",
                color=theme.INK_SOFT,
                font_family="ui-monospace, monospace",
            )
        ),
        rx.table.cell(
            rx.text(
                row["change"],
                size="1",
                color=theme.INK_MUTED,
                font_family="ui-monospace, monospace",
            )
        ),
        rx.table.cell(rx.text(row["actor"], size="1", color=theme.INK_SOFT)),
        rx.table.cell(
            rx.text(
                row["scenario"],
                size="1",
                color=theme.INK_MUTED,
                font_family="ui-monospace, monospace",
            )
        ),
        rx.table.cell(
            rx.text(rx.moment(row["created_at"], from_now=True), size="1", color=theme.INK_MUTED)
        ),
    )


def audit_trail():
    return theme.surface_card(
        rx.vstack(
            theme.section_heading(
                "Control-plane audit trail",
                "Every policy and health change, with the actor and the scenario that caused it",
            ),
            rx.cond(
                DashboardState.audit_rows.length() > 0,
                rx.box(
                    rx.table.root(
                        rx.table.header(
                            rx.table.row(
                                *[
                                    rx.table.column_header_cell(name)
                                    for name in (
                                        "Change",
                                        "Resource",
                                        "Before → after",
                                        "Actor",
                                        "Scenario",
                                        "When",
                                    )
                                ]
                            )
                        ),
                        rx.table.body(rx.foreach(DashboardState.audit_rows, _audit_row)),
                        variant="ghost",
                        width="100%",
                    ),
                    width="100%",
                    overflow_x="auto",
                    max_height="320px",
                    overflow_y="auto",
                ),
                theme.empty_state(
                    "file-clock",
                    "No control-plane changes yet. Take a service down, or run the Survive act.",
                ),
            ),
            width="100%",
            spacing="3",
            align="start",
        )
    )


def decision_log():
    return theme.surface_card(
        rx.vstack(
            theme.section_heading(
                "Decision log",
                "Who asked, for what, what was decided, and why",
                rx.flex(
                    *[_filter_chip(action) for action in ACTION_FILTERS],
                    spacing="2",
                    wrap="wrap",
                ),
            ),
            rx.cond(
                DashboardState.filtered_events.length() > 0,
                rx.box(
                    rx.table.root(
                        rx.table.header(
                            rx.table.row(
                                *[
                                    rx.table.column_header_cell(name)
                                    for name in (
                                        "Decision",
                                        "Agent",
                                        "Domain",
                                        "Answer / reason",
                                        "Source",
                                        "When",
                                    )
                                ]
                            )
                        ),
                        rx.table.body(rx.foreach(DashboardState.filtered_events, _event_row)),
                        variant="ghost",
                        width="100%",
                    ),
                    width="100%",
                    overflow_x="auto",
                    max_height="460px",
                    overflow_y="auto",
                ),
                theme.empty_state("scroll-text", "No decisions match this filter yet."),
            ),
            width="100%",
            spacing="3",
            align="start",
        )
    )
