# SPDX-License-Identifier: EUPL-1.2
"""Description of the team settings, shared basis for the CLI and the web UI."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any

from foresprint.calendar import countries, subdivisions
from foresprint.i18n import t
from foresprint.model import Numbering, ProductBasis, Team, TrendMode, Unit

# Federal states as spelled by the holidays library.
REGIONS: dict[str, str] = {
    "BW": "Baden-Württemberg",
    "BY": "Bayern",
    "BE": "Berlin",
    "BB": "Brandenburg",
    "HB": "Bremen",
    "HH": "Hamburg",
    "HE": "Hessen",
    "MV": "Mecklenburg-Vorpommern",
    "NI": "Niedersachsen",
    "NW": "Nordrhein-Westfalen",
    "RP": "Rheinland-Pfalz",
    "SL": "Saarland",
    "SN": "Sachsen",
    "ST": "Sachsen-Anhalt",
    "SH": "Schleswig-Holstein",
    "TH": "Thüringen",
}


class Kind(StrEnum):
    TEXT = "text"
    CHOICE = "choice"
    INT = "int"
    NUMBER = "number"
    # Share 0-1, prompted for and displayed as a percentage.
    PERCENT = "percent"
    DATE = "date"


class _LazyCountries(Mapping[str, str]):
    """Country choices, read from the holidays library on first use (importing it takes ~80 ms,
    which every command line start and every Tab completion would otherwise pay)."""

    def _all(self) -> dict[str, str]:
        return countries()

    def __getitem__(self, key: str) -> str:
        return self._all()[key]

    def __iter__(self):
        return iter(self._all())

    def __len__(self) -> int:
        return len(self._all())


@dataclass(frozen=True)
class Setting:
    key: str
    label: str
    help: str
    kind: Kind
    get: Callable[[Team], Any]
    set: Callable[[Team, Any], None]
    choices: Mapping[str, str] | None = None
    minimum: float | None = None
    maximum: float | None = None
    optional: bool = False
    # Only relevant as long as no sprint file exists yet.
    only_without_sprints: bool = False
    # Retroactively changes the calculation of all sprints.
    retroactive: bool = False
    # Step size in the web UI input field (otherwise by kind).
    step: float | None = None

    @property
    def title(self) -> str:
        """Label in the configured language."""
        return t(self.label)

    @property
    def text(self) -> str:
        """Explanation in the configured language."""
        return t(self.help)

    @property
    def options(self) -> dict[str, str] | None:
        """Choices with translated descriptions."""
        if self.choices is None:
            return None
        return {k: v if self is _COUNTRY else t(v) for k, v in self.choices.items()}

    def parse(self, raw: str) -> Any:
        """Convert a text input into the value; raise ValueError with a translated message."""
        raw = raw.strip()
        if raw == "":
            if self.optional:
                return None
            raise ValueError(t("Please enter a value."))
        match self.kind:
            case Kind.TEXT:
                if self.key == "capacity.region":
                    raw = raw.upper()
                    known = {c for code in countries() for c in subdivisions(code)}
                    if raw not in known:
                        raise ValueError(t("Unknown region code: {value}", value=raw))
                if self.key == "sprint.first_id":
                    from foresprint.storage import file_name_problem

                    # The ID becomes the file name; whatever the load path rejects must not
                    # be savable here (or the team could no longer be loaded afterwards).
                    if problem := file_name_problem(raw, portable=False):
                        raise ValueError(
                            t("ID not allowed as a file name ({problem}).", problem=problem)
                        )
                return raw
            case Kind.CHOICE:
                assert self.choices is not None
                value = raw.upper() if raw.upper() in self.choices else raw
                if self.choices is SWITCH:
                    value = _SWITCH_ALIASES.get(value.lower(), value)  # an/aus: German UI
                if value not in self.choices:
                    raise ValueError(t("Allowed: {values}", values=", ".join(self.choices)))
                return value
            case Kind.DATE:
                try:
                    return date.fromisoformat(raw)
                except ValueError as e:
                    raise ValueError(t("Enter the date as YYYY-MM-DD.")) from e
            case Kind.INT | Kind.NUMBER | Kind.PERCENT:
                try:
                    number = float(raw.replace(",", ".").removesuffix("%").strip())
                except ValueError as e:
                    raise ValueError(t("Please enter a number.")) from e
                if not math.isfinite(number):
                    raise ValueError(t("Please enter a finite number."))
                if self.kind is Kind.INT and not number.is_integer():
                    raise ValueError(t("Please enter a whole number."))
                self.check_range(number)
                if self.kind is Kind.INT:
                    return int(number)
                return number / 100 if self.kind is Kind.PERCENT else number
        raise AssertionError(self.kind)

    def check_range(self, shown: float) -> None:
        if self.minimum is not None and shown < self.minimum:
            raise ValueError(t("The value must be ≥ {value}.", value=_plain(self.minimum)))
        if self.maximum is not None and shown > self.maximum:
            raise ValueError(t("The value must be ≤ {value}.", value=_plain(self.maximum)))

    def display(self, team: Team) -> str:
        """Current value as text, the way it would be entered."""
        value = self.get(team)
        if value is None:
            return ""
        if self.kind is Kind.PERCENT:
            return _plain(round(value * 100, 6))
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, float):
            return _plain(value)
        return str(value)


def _plain(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def _setter(path: str, convert: Callable[[Any], Any] = lambda v: v) -> Callable[[Team, Any], None]:
    section, _, attr = path.rpartition(".")

    def apply(team: Team, value: Any) -> None:
        target = getattr(team, section) if section else team
        setattr(target, attr, None if value is None else convert(value))

    return apply


def _getter(path: str) -> Callable[[Team], Any]:
    section, _, attr = path.rpartition(".")
    return lambda team: getattr(getattr(team, section) if section else team, attr)


def _switch(path: str) -> Callable[[Team], str]:
    get = _getter(path)
    return lambda team: "on" if get(team) else "off"


def _switch_setter(path: str) -> Callable[[Team, Any], None]:
    section, _, attr = path.rpartition(".")

    def apply(team: Team, value: Any) -> None:
        setattr(getattr(team, section), attr, value == "on")
        getattr(team, section).explicit = True

    return apply


SWITCH = {"off": "off", "on": "on"}
_SWITCH_ALIASES = {"an": "on", "aus": "off"}

SETTINGS: list[Setting] = [
    Setting(
        key="name",
        label="Display name",
        help="Team name in reports and headings.",
        kind=Kind.TEXT,
        get=_getter("name"),
        set=_setter("name"),
    ),
    Setting(
        key="unit",
        label="Estimation unit",
        help=(
            "PT (person days) or SP (story points). Only affects the display; the "
            "capacity is always in PT."
        ),
        kind=Kind.CHOICE,
        choices={"PT": "person days", "SP": "story points"},
        get=lambda t: t.unit.value,
        set=_setter("unit", Unit),
    ),
    Setting(
        key="features.products",
        label="Product distribution",
        help=(
            "Only needed if the team looks after several products and the sprint amount "
            "is distributed over them: product list, PO pre-planning, planning and done "
            "per product, default distribution and balance. Off: these pages and inputs "
            "are omitted; values already recorded stay in the files."
        ),
        kind=Kind.CHOICE,
        choices=SWITCH,
        get=_switch("features.products"),
        set=_switch_setter("features.products"),
    ),
    Setting(
        key="features.po",
        label="PO assignment",
        help=(
            "Each product has a responsible product owner; the pre-planning shows sums "
            "per PO. Only useful together with the product distribution. Off: there is no "
            "PO column and no sums per PO."
        ),
        kind=Kind.CHOICE,
        choices=SWITCH,
        get=_switch("features.po"),
        set=_switch_setter("features.po"),
    ),
    Setting(
        key="features.production",
        label="Production access",
        help=(
            "Only some of the people may work on tickets that need production access. On: "
            "people are marked as authorized, planning and review record how much of the "
            "amount needs production access, and a bottleneck hint shows whether the "
            "authorized group can handle it. Off: no marking, no inputs, no hint."
        ),
        kind=Kind.CHOICE,
        choices=SWITCH,
        get=_switch("features.production"),
        set=_switch_setter("features.production"),
    ),
    Setting(
        key="features.tickets",
        label="Ticket pre-planning",
        help=(
            "Tickets from the issue tracker (Jira or CSV export) are assigned to projects "
            "and distributed over future sprints: project list with target date, earmarks "
            "per sprint, project traffic light and refinement list (files projects.yaml, "
            "tickets.yaml, preplan.yaml; section tracker in team.yaml). Off: the files "
            "are not read, and there is no page and no command for it."
        ),
        kind=Kind.CHOICE,
        choices=SWITCH,
        get=_switch("features.tickets"),
        set=_switch_setter("features.tickets"),
    ),
    Setting(
        key="capacity.country",
        label="Country",
        help=(
            "For public holidays and the weekend (ISO country code, e.g. DE, AT, CH, US, "
            "GB, SA). Individual people can have a different country in the people list."
        ),
        kind=Kind.CHOICE,
        choices=_LazyCountries(),
        get=_getter("capacity.country"),
        set=_setter("capacity.country"),
        retroactive=True,
    ),
    Setting(
        key="capacity.region",
        label="Region (state, province)",
        help=(
            "For regional public holidays, e.g. NW (Germany), CA (USA), ON (Canada). "
            "Empty = nationwide holidays only. Must match the country; individual people "
            "can differ."
        ),
        kind=Kind.TEXT,
        optional=True,
        get=_getter("capacity.region"),
        set=_setter("capacity.region"),
        retroactive=True,
    ),
    Setting(
        key="capacity.workweek",
        label="Work week",
        help=(
            'Which days count as working days. "auto" follows the country (e.g. Sunday '
            "to Thursday in Saudi Arabia)."
        ),
        kind=Kind.CHOICE,
        choices={
            "auto": "as in the country",
            "mon-fri": "Monday to Friday",
            "sun-thu": "Sunday to Thursday",
            "mon-sat": "Monday to Saturday",
        },
        get=_getter("capacity.workweek"),
        set=_setter("capacity.workweek"),
        retroactive=True,
    ),
    Setting(
        key="capacity.overhead_share",
        label="Scrum events deduction (%)",
        help=(
            "Flat share of the capacity for dailies, planning, review, retro, refinement. "
            "0 if the absences already cover this."
        ),
        kind=Kind.PERCENT,
        minimum=0,
        maximum=90,
        get=_getter("capacity.overhead_share"),
        set=_setter("capacity.overhead_share", float),
    ),
    Setting(
        key="capacity.overhead_days",
        label="Scrum events deduction (PT per person)",
        help=(
            "Fixed deduction per sprint and full-time person (part time pro rata), e.g. 1 "
            "for planning, review and retro. Equals the deduction in % (both fields stay "
            "in sync); 0 = the deduction in % applies."
        ),
        kind=Kind.NUMBER,
        minimum=0,
        maximum=20,
        step=0.25,
        get=_getter("capacity.overhead_days"),
        set=_setter("capacity.overhead_days", float),
    ),
    Setting(
        key="capacity.absence_history",
        label="Absence history (number of sprints)",
        help=(
            "For future sprints without known absences the capacity from calendar and "
            "people list is reduced by the average absences of the last that many sprints "
            "with confirmed absences. 0 = no estimate (no deduction for absences)."
        ),
        kind=Kind.INT,
        minimum=0,
        maximum=26,
        get=_getter("capacity.absence_history"),
        set=_setter("capacity.absence_history", int),
        retroactive=True,
    ),
    Setting(
        key="sprint.length_days",
        label="Sprint length (calendar days)",
        help="Applies to newly created sprints; recorded sprints keep their dates.",
        kind=Kind.INT,
        minimum=1,
        maximum=56,
        get=_getter("sprint.length_days"),
        set=_setter("sprint.length_days", int),
    ),
    Setting(
        key="sprint.numbering",
        label="Sprint numbering",
        help="Scheme for newly created sprint IDs.",
        kind=Kind.CHOICE,
        choices={"yearly": "per year (2026.1, 2026.2 …)", "sequential": ("sequential (1, 2, 3 …)")},
        get=lambda t: t.sprint.numbering.value,
        set=_setter("sprint.numbering", Numbering),
    ),
    Setting(
        key="sprint.first_start",
        label="Start of the first sprint",
        help="Only needed as long as no sprint file exists.",
        kind=Kind.DATE,
        optional=True,
        only_without_sprints=True,
        get=_getter("sprint.first_start"),
        set=_setter("sprint.first_start"),
    ),
    Setting(
        key="sprint.first_id",
        label="ID of the first sprint",
        help=(
            "The sprint that is running now or starts next, e.g. 2026.15 or 15. Only "
            "needed as long as no sprint file exists; after that: Change sprint IDs."
        ),
        kind=Kind.TEXT,
        optional=True,
        only_without_sprints=True,
        get=_getter("sprint.first_id"),
        set=_setter("sprint.first_id"),
    ),
    Setting(
        key="forecast.reference_capacity",
        label="Reference capacity (PT)",
        help=(
            "Display scale of the normalized velocity (norm. velocity = focus factor × "
            "reference capacity). Best the capacity of a fully staffed sprint. It cancels "
            "out in the calculation: changes all normalized values but not the Forecast "
            "PLAN."
        ),
        kind=Kind.NUMBER,
        minimum=1,
        retroactive=True,
        get=_getter("forecast.reference_capacity"),
        set=_setter("forecast.reference_capacity", float),
    ),
    Setting(
        key="forecast.window",
        label="Ø over sprints",
        help=(
            "Number of sprints in the moving average. Smaller = reacts faster, larger = smoother."
        ),
        kind=Kind.INT,
        minimum=1,
        maximum=20,
        retroactive=True,
        get=_getter("forecast.window"),
        set=_setter("forecast.window", int),
    ),
    Setting(
        key="forecast.trend_mode",
        label="Trend mode",
        help=(
            "How the average is extrapolated into the future. “Constant” is robust and "
            "the default. “Linear” and “classic” also extrapolate noise: they can rise or "
            "fall and only make sense for a proven, stable trend."
        ),
        kind=Kind.CHOICE,
        choices={
            "flat": "last average stays constant (default)",
            "classic": "linear, then multiplicative, then linear (caution: extrapolates noise)",
            "linear": "linear throughout (caution: extrapolates noise)",
        },
        retroactive=True,
        get=lambda t: t.forecast.trend_mode.value,
        set=_setter("forecast.trend_mode", TrendMode),
    ),
    Setting(
        key="forecast.roadmap_share",
        label="Plannable share (%)",
        help=(
            'Share of the Forecast PLAN reserved for plannable topics; the rest is "small items".'
        ),
        kind=Kind.PERCENT,
        minimum=0,
        maximum=100,
        get=_getter("forecast.roadmap_share"),
        set=_setter("forecast.roadmap_share", float),
    ),
    Setting(
        key="forecast.horizon",
        label="Forecast horizon (sprints)",
        help="How many future sprints appear in the forecast and report.",
        kind=Kind.INT,
        minimum=1,
        maximum=26,
        get=_getter("forecast.horizon"),
        set=_setter("forecast.horizon", int),
    ),
    Setting(
        key="forecast.rounding",
        label="Decimal places Forecast PLAN",
        help=(
            "The Forecast PLAN is rounded down to this many digits: it is the planning "
            "quantity, and rounding down guards against over-planning. Capacity, by "
            "contrast, is calculated unrounded internally and only rounded half-up when "
            "shown and stored, so the denominator of the normalized velocity is not "
            "systematically too small."
        ),
        kind=Kind.INT,
        minimum=0,
        maximum=3,
        get=_getter("forecast.rounding"),
        set=_setter("forecast.rounding", int),
    ),
    Setting(
        key="forecast.product_basis",
        label="Standard distribution per product based on",
        help=(
            "Which amount is distributed equally across the products handled (standard = "
            "amount / number of products)."
        ),
        kind=Kind.CHOICE,
        choices={
            "plan": "entire Forecast PLAN",
            "roadmap": "plannable share only (small items stay across products)",
        },
        get=lambda t: t.forecast.product_basis.value,
        set=_setter("forecast.product_basis", ProductBasis),
    ),
]

BY_KEY = {s.key: s for s in SETTINGS}
# The first sprint is asked for first when creating a team (in this order).
FIRST_SPRINT_KEYS = ("sprint.numbering", "sprint.first_start", "sprint.first_id")
# Country names stay untranslated (proper names).
_COUNTRY = BY_KEY["capacity.country"]


def applicable(has_sprints: bool) -> list[Setting]:
    return [s for s in SETTINGS if not (s.only_without_sprints and has_sprints)]


def changes(before: Team, after: Team) -> list[tuple[Setting, str, str]]:
    """Changed settings as (setting, old, new)."""
    return [
        (s, s.display(before), s.display(after))
        for s in SETTINGS
        if s.display(before) != s.display(after)
    ]
