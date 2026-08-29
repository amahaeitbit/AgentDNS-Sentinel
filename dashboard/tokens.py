"""Colour and label constants, free of any UI framework so they can be tested.

The four status colours are fixed in both light and dark. The traffic bar's
segment order (ALLOW, THROTTLE, BLOCK, FAILURE) is the ordering that clears
colour-vision and normal-vision separation against both surfaces; changing it
means re-validating the palette.
"""

from __future__ import annotations

GOOD = "#0ca30c"
WARNING = "#fab219"
CRITICAL = "#d03b3b"
SERIOUS = "#ec835a"
NEUTRAL = "#898781"

# Categorical slots, used only for act identity - never for status. Assigned in
# this fixed order and never cycled: a sixth act takes slot 6, it does not reuse
# slot 1.
ACT_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#4a3aa7"]

# decision -> (colour, label, ink for text sitting on the fill)
ACTIONS: dict[str, tuple[str, str, str]] = {
    "ALLOW": (GOOD, "Allowed", "#0b0b0b"),
    "THROTTLE": (WARNING, "Throttled", "#0b0b0b"),
    "BLOCK": (CRITICAL, "Blocked", "#ffffff"),
    "SERVFAIL": (SERIOUS, "Failed", "#0b0b0b"),
    "NXDOMAIN": (SERIOUS, "No record", "#0b0b0b"),
}
UNKNOWN_ACTION = (NEUTRAL, "No traffic yet", "#ffffff")

# (decision key, summary field, colour, label, on-fill ink) in validated order.
COMPOSITION: list[tuple[str, str, str, str, str]] = [
    ("ALLOW", "allowed", GOOD, "Allowed", "#0b0b0b"),
    ("THROTTLE", "throttled", WARNING, "Throttled", "#0b0b0b"),
    ("BLOCK", "blocked", CRITICAL, "Blocked", "#ffffff"),
    ("FAILURE", "failures", SERIOUS, "Failed", "#0b0b0b"),
]

# A segment narrower than this cannot hold a readable direct label.
DIRECT_LABEL_MIN_PERCENT = 12.0
