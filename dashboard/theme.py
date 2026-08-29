"""Design tokens for the dashboard.

Surfaces and ink are mode-aware; the four status colours are fixed in both
modes. Segment order in the traffic bar is ALLOW -> THROTTLE -> BLOCK ->
FAILURE, which is the ordering that clears colour-vision and normal-vision
separation on both surfaces. Every status colour ships with an icon and a
label, so nothing is ever carried by hue alone.
"""

from __future__ import annotations

import reflex as rx

from .tokens import ACT_COLORS, CRITICAL, GOOD, SERIOUS, WARNING  # noqa: F401


def mode(light: str, dark: str):
    """A token that follows the viewer's colour mode."""
    return rx.color_mode_cond(light=light, dark=dark)


PAGE_BG = mode("#f9f9f7", "#0d0d0d")
SURFACE = mode("#fcfcfb", "#1a1a19")
SUNK = mode("#f1f0ea", "#131312")
INK = mode("#0b0b0b", "#ffffff")
INK_SOFT = mode("#52514e", "#c3c2b7")
INK_MUTED = "#898781"
HAIRLINE = mode("#e1e0d9", "#2c2c2a")
SHADOW = mode("0 1px 2px rgba(11,11,11,0.06)", "0 1px 2px rgba(0,0,0,0.5)")

def surface_card(*children, **props):
    """The one card treatment used across the page."""
    style = {
        "background": SURFACE,
        "border": rx.color_mode_cond(
            light="1px solid #e1e0d9", dark="1px solid #2c2c2a"
        ),
        "border_radius": "14px",
        "padding": "1.1rem 1.25rem",
        "box_shadow": SHADOW,
    }
    style.update(props)
    return rx.box(*children, **style)


def section_heading(title: str, subtitle: str = "", trailing=None):
    return rx.hstack(
        rx.vstack(
            rx.heading(title, size="4", color=INK),
            rx.cond(
                subtitle != "",
                rx.text(subtitle, size="2", color=INK_MUTED),
                rx.fragment(),
            ),
            spacing="1",
            align="start",
        ),
        rx.spacer(),
        trailing if trailing is not None else rx.fragment(),
        width="100%",
        align="center",
        wrap="wrap",
        spacing="3",
    )


def status_pill(label, icon, tone=None):
    """Icon plus label plus colour - never colour on its own.

    `icon` is a rendered component, not a name: Reflex needs a literal icon
    name at build time, so anything data-driven arrives here already resolved.
    """
    return rx.hstack(
        icon,
        rx.text(label, size="1", color=tone if tone is not None else INK_SOFT, weight="medium"),
        spacing="1",
        align="center",
        padding="0.15rem 0.5rem",
        border_radius="999px",
        background=SUNK,
        flex_shrink="0",
    )


def empty_state(icon: str, text: str):
    return rx.center(
        rx.vstack(
            rx.icon(icon, size=22, color=INK_MUTED),
            rx.text(text, size="2", color=INK_MUTED, text_align="center"),
            align="center",
            spacing="2",
        ),
        padding="2rem 1rem",
        width="100%",
    )
