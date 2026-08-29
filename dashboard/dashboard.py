"""The Reflex dashboard for AgentDNS Sentinel."""

from __future__ import annotations

import reflex as rx

from . import theme, views
from .state import DashboardState


def footer():
    return rx.hstack(
        rx.text(
            "Runloop Network Policies are the outer, non-bypassable egress boundary. "
            "This resolver is the fine-grained agent policy inside it.",
            size="1",
            color=theme.INK_MUTED,
            max_width="70ch",
        ),
        rx.spacer(),
        rx.text("docs/runloop.md", size="1", color=theme.INK_MUTED),
        width="100%",
        align="center",
        wrap="wrap",
        padding_y="1.5rem",
        border_top=rx.color_mode_cond(light="1px solid #e1e0d9", dark="1px solid #2c2c2a"),
        margin_top="1rem",
    )


def index():
    return rx.box(
        rx.vstack(
            views.header(),
            views.operator_workflow(),
            views.stat_row(),
            views.traffic_bar(),
            views.topology(),
            views.alerts_panel(),
            rx.grid(
                views.scenarios_section(),
                rx.box(
                    views.result_panel(),
                    position={"initial": "static", "xl": "sticky"},
                    top="9rem",
                    width="100%",
                ),
                grid_template_columns={
                    "initial": "minmax(0, 1fr)",
                    "xl": "minmax(0, 2.2fr) minmax(320px, 1fr)",
                },
                spacing="5",
                width="100%",
                align="start",
            ),
            views.decision_log(),
            views.audit_trail(),
            footer(),
            spacing="5",
            width="100%",
            max_width="1500px",
            margin="0 auto",
            padding_x={"initial": "1rem", "md": "2rem"},
            padding_bottom="2rem",
            align="start",
        ),
        min_height="100vh",
        background=theme.PAGE_BG,
        color=theme.INK,
    )


# The Radix theme is configured in rxconfig.py via RadixThemesPlugin.
app = rx.App(
    style={
        "font_family": (
            "Inter, ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif"
        ),
    },
    stylesheets=["https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap"],
)
app.add_page(
    index,
    title="AgentDNS Sentinel",
    description="Identity-aware DNS policy, quotas and failover for agents in one sandbox.",
    on_load=[DashboardState.refresh, DashboardState.poll],
)
