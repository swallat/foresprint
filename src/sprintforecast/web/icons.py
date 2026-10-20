"""Flat status icons for the web UI (Material icons in Markdown colour, no emojis).

Emojis render differently per platform (on Windows e.g. as large coloured squares) and clash
with the flat icons of the sidebar and buttons. Status is shown by icon plus colour.
"""

from __future__ import annotations

DONE_ICON = ":green[:material/check_circle:]"
OPEN_ICON = ":gray[:material/radio_button_unchecked:]"
WARNING_ICON = ":orange[:material/warning:]"


def status_icon(ok: bool) -> str:
    """Markdown for "done" (green check circle) or "open" (grey empty circle)."""
    return DONE_ICON if ok else OPEN_ICON
