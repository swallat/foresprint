"""Drag-and-drop board for the sprint columns of the tickets page: the cards of the future
sprints as columns, a card dragged onto another column is earmarked for that sprint, a card
dragged onto the release bar goes back to the automatic distribution.

A small Streamlit component (v2) with inline HTML, CSS and JavaScript; it only reports the
move (ticket, target sprint) and the page writes the same earmarks as the buttons and the form.
Card texts come from the tickets and are inserted as text, never as HTML."""

from __future__ import annotations

import textwrap
from collections.abc import Callable
from typing import Any

import streamlit as st

from sprintforecast.i18n import t
from sprintforecast.preplan import Distribution, Placement
from sprintforecast.storage import TeamData

# Value of a move onto the release bar (distribute automatically).
RELEASE = ""

HTML = """
<div class="board"></div>
<div class="release" data-sprint="">release</div>
"""

CSS = """
.board { display: flex; gap: 0.75rem; align-items: flex-start; overflow-x: auto; }
.column {
  flex: 1 1 0; min-width: 11rem; padding: 0.5rem; border-radius: var(--st-base-radius);
  background: var(--st-secondary-background-color); border: 1px dashed transparent;
}
.column.over, .release.over { border-color: var(--st-primary-color); }
.column h4 { margin: 0 0 0.25rem 0; color: var(--st-heading-color); font-size: 1rem; }
.fill { font-size: 0.8rem; opacity: 0.75; margin-bottom: 0.5rem; }
.bar { height: 0.35rem; border-radius: 0.2rem; background: var(--st-border-color);
  margin-bottom: 0.5rem; overflow: hidden; }
.bar > div { height: 100%; background: var(--st-primary-color); }
.card {
  padding: 0.4rem 0.5rem; margin-bottom: 0.4rem; border-radius: var(--st-base-radius);
  background: var(--st-background-color); color: var(--st-text-color);
  border: 1px solid var(--st-border-color); cursor: grab; font-size: 0.85rem;
}
.card.fixed { cursor: default; border-style: dotted; }
.card.fixed .key { font-weight: 700; }
.card.dragging { opacity: 0.4; }
.card .meta { font-size: 0.75rem; opacity: 0.75; }
.card .key { font-weight: 600; }
.release {
  margin-top: 0.75rem; padding: 0.6rem; text-align: center; border-radius: var(--st-base-radius);
  border: 1px dashed var(--st-border-color); color: var(--st-text-color); font-size: 0.85rem;
}
.more { font-size: 0.75rem; opacity: 0.75; }
"""

JS = """
export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  const board = parentElement.querySelector(".board");
  const release = parentElement.querySelector(".release");
  board.replaceChildren();
  release.textContent = data.releaseText;
  const text = (tag, cls, value) => {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    el.textContent = value;
    return el;
  };
  const allow = (zone) => {
    zone.ondragover = (e) => { e.preventDefault(); zone.classList.add("over"); };
    zone.ondragleave = (e) => {
      if (!zone.contains(e.relatedTarget)) zone.classList.remove("over");
    };
    zone.ondrop = (e) => {
      e.preventDefault();
      zone.classList.remove("over");
      const ticket = e.dataTransfer.getData("text/plain");
      const sprint = zone.dataset.sprint;
      if (ticket) setTriggerValue("moved", { ticket: ticket, sprint: sprint });
    };
  };
  for (const col of data.columns) {
    const zone = document.createElement("div");
    zone.className = "column";
    zone.dataset.sprint = col.id;
    zone.appendChild(text("h4", "", col.id));
    for (const line of col.fill) {
      zone.appendChild(text("div", "fill", line.text));
      const bar = document.createElement("div");
      bar.className = "bar";
      const inner = document.createElement("div");
      inner.style.width = Math.round(Math.min(1, line.ratio) * 100) + "%";
      bar.appendChild(inner);
      zone.appendChild(bar);
    }
    for (const card of col.cards) {
      const el = document.createElement("div");
      el.className = "card " + card.mode;
      el.appendChild(text("span", "key", card.key));
      el.appendChild(document.createTextNode(" " + card.title));
      el.appendChild(text("div", "meta", card.meta));
      if (card.mode !== "fixed") {
        el.draggable = true;
        el.ondragstart = (e) => {
          e.dataTransfer.setData("text/plain", card.key);
          e.dataTransfer.effectAllowed = "move";
          el.classList.add("dragging");
        };
        el.ondragend = () => el.classList.remove("dragging");
      }
      zone.appendChild(el);
    }
    if (col.more > 0) zone.appendChild(text("div", "more", col.moreText));
    allow(zone);
    board.appendChild(zone);
  }
  allow(release);
}
"""

_BOARD = st.components.v2.component("sprintforecast_board", html=HTML, css=CSS, js=JS)


def board_data(
    data: TeamData,
    dist: Distribution,
    shown: list[str],
    visible: Callable[[Placement], bool],
    describe: Callable[[Placement], str],
    card_limit: int,
) -> dict[str, Any]:
    """What the component draws: per sprint its fill lines and its cards. ``visible`` tells
    whether a placement passes the page filter, ``describe`` gives the second line of a card."""
    columns = []
    for sprint in shown:
        fill = []
        for b in (x for x in dist.budgets if x.sprint == sprint):
            name = next((p.name for p in data.products if p.id == b.product), None)
            prefix = f"{name}: " if name and len(data.products) > 1 else ""
            used = b.fixed + b.placed
            fill.append(
                {
                    "text": f"{prefix}{_num(used)} / {_num(b.base)}",
                    "ratio": used / b.base if b.base > 0 else 0.0,
                }
            )
        placements = [p for p in dist.in_sprint(sprint) if visible(p)]
        cards = []
        for p in placements[:card_limit]:
            ticket = data.ticket(p.ticket)
            title = textwrap.shorten(ticket.title if ticket else "", 38, placeholder="…")
            cards.append(
                {
                    "key": p.ticket,
                    "title": title,
                    "meta": describe(p),
                    "mode": {"fixed_sprint": "fixed", "earmark": "earmark"}.get(p.reason, "placed"),
                }
            )
        more = max(0, len(placements) - card_limit)
        columns.append(
            {
                "id": sprint,
                "fill": fill,
                "cards": cards,
                "more": more,
                "moreText": t("… and {count} more", count=more),
            }
        )
    return {"columns": columns, "releaseText": t("Drop here to distribute automatically (release)")}


def _num(value: float | None) -> str:
    if value is None:
        return "–"
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


def sprint_board(
    data: TeamData,
    dist: Distribution,
    shown: list[str],
    visible: Callable[[Placement], bool],
    describe: Callable[[Placement], str],
    card_limit: int,
    key: str,
) -> tuple[str, str] | None:
    """Draws the board; returns ``(ticket, sprint)`` of a card that was just dropped (sprint
    ``RELEASE`` = release the earmark), else None."""
    result = _BOARD(
        key=key,
        data=board_data(data, dist, shown, visible, describe, card_limit),
        on_moved_change=lambda: None,
    )
    moved = result.moved
    if not isinstance(moved, dict) or "ticket" not in moved or "sprint" not in moved:
        return None
    return str(moved["ticket"]), str(moved["sprint"])
