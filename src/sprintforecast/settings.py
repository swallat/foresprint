# SPDX-License-Identifier: EUPL-1.2
"""Beschreibung der Team-Einstellungen – gemeinsame Grundlage für CLI und Weboberfläche."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any

from sprintforecast.calendar import countries, subdivisions
from sprintforecast.i18n import t
from sprintforecast.model import Numbering, ProductBasis, Team, TrendMode, Unit

# Bundesländer in der Schreibweise der holidays-Bibliothek.
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
    # Anteil 0–1, wird in Prozent abgefragt und angezeigt.
    PERCENT = "percent"
    DATE = "date"


@dataclass(frozen=True)
class Setting:
    key: str
    label: str
    help: str
    kind: Kind
    get: Callable[[Team], Any]
    set: Callable[[Team, Any], None]
    choices: dict[str, str] | None = None
    minimum: float | None = None
    maximum: float | None = None
    optional: bool = False
    # Nur relevant, solange noch keine Sprintdatei existiert.
    only_without_sprints: bool = False
    # Ändert rückwirkend die Berechnung aller Sprints.
    retroactive: bool = False
    # Schrittweite im Eingabefeld der Weboberfläche (sonst je Art).
    step: float | None = None

    @property
    def title(self) -> str:
        """Bezeichnung in der eingestellten Sprache."""
        return t(self.label)

    @property
    def text(self) -> str:
        """Erklärung in der eingestellten Sprache."""
        return t(self.help)

    @property
    def options(self) -> dict[str, str] | None:
        """Auswahlmöglichkeiten mit übersetzten Beschreibungen."""
        if self.choices is None:
            return None
        return {k: v if self is _COUNTRY else t(v) for k, v in self.choices.items()}

    def parse(self, raw: str) -> Any:
        """Wandelt eine Texteingabe in den Wert um; wirft ValueError mit deutscher Meldung."""
        raw = raw.strip()
        if raw == "":
            if self.optional:
                return None
            raise ValueError(t("Bitte einen Wert eingeben."))
        match self.kind:
            case Kind.TEXT:
                if self.key == "capacity.region":
                    raw = raw.upper()
                    known = {c for code in countries() for c in subdivisions(code)}
                    if raw not in known:
                        raise ValueError(t("Unbekannter Regionscode: {value}", value=raw))
                if self.key == "sprint.first_id":
                    from sprintforecast.storage import file_name_problem

                    # Die ID wird zum Dateinamen; was der Ladeweg ablehnt, darf hier nicht
                    # speicherbar sein (sonst ließe sich das Team danach nicht mehr laden).
                    if problem := file_name_problem(raw, portable=False):
                        raise ValueError(
                            t("ID nicht zulässig als Dateiname ({problem}).", problem=problem)
                        )
                return raw
            case Kind.CHOICE:
                assert self.choices is not None
                value = raw.upper() if raw.upper() in self.choices else raw
                if value not in self.choices:
                    raise ValueError(t("Erlaubt: {values}", values=", ".join(self.choices)))
                return value
            case Kind.DATE:
                try:
                    return date.fromisoformat(raw)
                except ValueError as e:
                    raise ValueError(t("Datum im Format JJJJ-MM-TT eingeben.")) from e
            case Kind.INT | Kind.NUMBER | Kind.PERCENT:
                try:
                    number = float(raw.replace(",", ".").removesuffix("%").strip())
                except ValueError as e:
                    raise ValueError(t("Bitte eine Zahl eingeben.")) from e
                if not math.isfinite(number):
                    raise ValueError(t("Bitte eine endliche Zahl eingeben."))
                if self.kind is Kind.INT and not number.is_integer():
                    raise ValueError(t("Bitte eine ganze Zahl eingeben."))
                self.check_range(number)
                if self.kind is Kind.INT:
                    return int(number)
                return number / 100 if self.kind is Kind.PERCENT else number
        raise AssertionError(self.kind)

    def check_range(self, shown: float) -> None:
        if self.minimum is not None and shown < self.minimum:
            raise ValueError(t("Der Wert muss ≥ {value} sein.", value=_plain(self.minimum)))
        if self.maximum is not None and shown > self.maximum:
            raise ValueError(t("Der Wert muss ≤ {value} sein.", value=_plain(self.maximum)))

    def display(self, team: Team) -> str:
        """Aktueller Wert als Text, so wie er auch eingegeben würde."""
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
    return lambda team: "an" if get(team) else "aus"


def _switch_setter(path: str) -> Callable[[Team, Any], None]:
    section, _, attr = path.rpartition(".")

    def apply(team: Team, value: Any) -> None:
        setattr(getattr(team, section), attr, value == "an")
        getattr(team, section).explicit = True

    return apply


SWITCH = {"aus": "aus", "an": "an"}

SETTINGS: list[Setting] = [
    Setting(
        key="name",
        label="Anzeigename",
        help="Name des Teams in Berichten und Überschriften.",
        kind=Kind.TEXT,
        get=_getter("name"),
        set=_setter("name"),
    ),
    Setting(
        key="unit",
        label="Schätzeinheit",
        help="PT (Personentage) oder SP (Story Points). Wirkt nur auf die Anzeige; "
        "die Kapazität ist immer in PT.",
        kind=Kind.CHOICE,
        choices={"PT": "Personentage", "SP": "Story Points"},
        get=lambda t: t.unit.value,
        set=_setter("unit", Unit),
    ),
    Setting(
        key="features.products",
        label="Produktverteilung",
        help="Nur nötig, wenn das Team mehrere Produkte betreut und die Sprint-Menge darauf "
        "verteilt wird: Produktliste, PO-Vorplanung, Planning und Erledigt je Produkt, "
        "Standardverteilung und Saldo. Aus: Diese Seiten und Eingaben entfallen; bereits "
        "erfasste Werte bleiben in den Dateien erhalten.",
        kind=Kind.CHOICE,
        choices=SWITCH,
        get=_switch("features.products"),
        set=_switch_setter("features.products"),
    ),
    Setting(
        key="features.po",
        label="Zuordnung PO",
        help="Jedes Produkt hat einen verantwortlichen Product Owner; die Vorplanung zeigt "
        "Summen je PO. Sinnvoll nur zusammen mit der Produktverteilung. Aus: Es gibt keine "
        "Spalte PO und keine Summen je PO.",
        kind=Kind.CHOICE,
        choices=SWITCH,
        get=_switch("features.po"),
        set=_switch_setter("features.po"),
    ),
    Setting(
        key="features.production",
        label="Produktionszugriff",
        help="Nur ein Teil der Personen darf Tickets mit Produktionszugriff bearbeiten. An: "
        "Personen werden als berechtigt markiert, im Planning und Review wird erfasst, wie "
        "viel Menge davon Produktionszugriff braucht, und ein Engpass-Hinweis zeigt, ob die "
        "berechtigte Gruppe das schafft. Aus: keine Markierung, keine Eingaben, kein Hinweis.",
        kind=Kind.CHOICE,
        choices=SWITCH,
        get=_switch("features.production"),
        set=_switch_setter("features.production"),
    ),
    Setting(
        key="features.tickets",
        label="Ticket-Vorplanung",
        help="Tickets aus dem Ticketsystem (CSV-Export) werden Projekten zugeordnet und auf "
        "künftige Sprints verteilt: Projektliste mit Zieldatum, Vormerkungen je Sprint, "
        "Projektampel und Refinement-Liste (Dateien projects.yaml, tickets.yaml, preplan.yaml; "
        "Abschnitt tracker in team.yaml). Aus: Die Dateien werden nicht gelesen, es gibt keine "
        "Seite und keinen Befehl dafür.",
        kind=Kind.CHOICE,
        choices=SWITCH,
        get=_switch("features.tickets"),
        set=_switch_setter("features.tickets"),
    ),
    Setting(
        key="capacity.country",
        label="Land",
        help="Für die Feiertage und das Wochenende (ISO-Ländercode, z. B. DE, AT, CH, US, GB, "
        "SA). Einzelne Personen können in der Personenliste ein anderes Land haben.",
        kind=Kind.CHOICE,
        choices=countries(),
        get=_getter("capacity.country"),
        set=_setter("capacity.country"),
        retroactive=True,
    ),
    Setting(
        key="capacity.region",
        label="Region (Bundesland, Staat, Provinz)",
        help="Für regionale Feiertage, z. B. NW (Deutschland), CA (USA), ON (Kanada). Leer = nur "
        "landesweite Feiertage. Muss zum Land passen; einzelne Personen können abweichen.",
        kind=Kind.TEXT,
        optional=True,
        get=_getter("capacity.region"),
        set=_setter("capacity.region"),
        retroactive=True,
    ),
    Setting(
        key="capacity.workweek",
        label="Arbeitswoche",
        help="Welche Tage als Arbeitstage zählen. „auto“ folgt dem Land (z. B. Sonntag bis "
        "Donnerstag in Saudi-Arabien).",
        kind=Kind.CHOICE,
        choices={
            "auto": "wie im Land",
            "mon-fri": "Montag bis Freitag",
            "sun-thu": "Sonntag bis Donnerstag",
            "mon-sat": "Montag bis Samstag",
        },
        get=_getter("capacity.workweek"),
        set=_setter("capacity.workweek"),
        retroactive=True,
    ),
    Setting(
        key="capacity.overhead_share",
        label="Abzug für Scrum-Termine (%)",
        help="Pauschaler Anteil der Kapazität für Dailys, Planning, Review, Retro, Refinement. "
        "0, wenn die Fehltage das bereits abdecken.",
        kind=Kind.PERCENT,
        minimum=0,
        maximum=90,
        get=_getter("capacity.overhead_share"),
        set=_setter("capacity.overhead_share", float),
    ),
    Setting(
        key="capacity.overhead_days",
        label="Abzug für Scrum-Termine (PT je Person)",
        help="Fester Abzug je Sprint und Vollzeitperson (Teilzeit anteilig), z. B. 1 für "
        "Planning, Review und Retro. Entspricht dem Abzug in % (beide Felder gleichen sich ab); "
        "0 = der Abzug in % gilt.",
        kind=Kind.NUMBER,
        minimum=0,
        maximum=20,
        step=0.25,
        get=_getter("capacity.overhead_days"),
        set=_setter("capacity.overhead_days", float),
    ),
    Setting(
        key="capacity.absence_history",
        label="Fehltage-Historie (Anzahl Sprints)",
        help="Für künftige Sprints ohne bekannte Fehltage wird die Kapazität aus Kalender und "
        "Personenliste um die durchschnittlichen Fehltage der letzten so vielen Sprints mit "
        "bestätigten Fehltagen gemindert. 0 = keine Schätzung (ohne Abzug für Fehltage).",
        kind=Kind.INT,
        minimum=0,
        maximum=26,
        get=_getter("capacity.absence_history"),
        set=_setter("capacity.absence_history", int),
        retroactive=True,
    ),
    Setting(
        key="sprint.length_days",
        label="Sprintlänge (Kalendertage)",
        help="Gilt für neu erzeugte Sprints; bereits erfasste Sprints behalten ihre Daten.",
        kind=Kind.INT,
        minimum=1,
        maximum=56,
        get=_getter("sprint.length_days"),
        set=_setter("sprint.length_days", int),
    ),
    Setting(
        key="sprint.numbering",
        label="Sprint-Nummerierung",
        help="Schema für neu erzeugte Sprint-IDs.",
        kind=Kind.CHOICE,
        choices={"yearly": "pro Jahr (2026.1, 2026.2 …)", "sequential": "fortlaufend (1, 2, 3 …)"},
        get=lambda t: t.sprint.numbering.value,
        set=_setter("sprint.numbering", Numbering),
    ),
    Setting(
        key="sprint.first_start",
        label="Start des ersten Sprints",
        help="Nur nötig, solange noch keine Sprintdatei existiert.",
        kind=Kind.DATE,
        optional=True,
        only_without_sprints=True,
        get=_getter("sprint.first_start"),
        set=_setter("sprint.first_start"),
    ),
    Setting(
        key="sprint.first_id",
        label="ID des ersten Sprints",
        help="Der Sprint, der gerade läuft oder als Nächstes beginnt, z. B. 2026.15 oder 15. "
        "Nur nötig, solange noch keine Sprintdatei existiert; danach: Sprint-IDs ändern.",
        kind=Kind.TEXT,
        optional=True,
        only_without_sprints=True,
        get=_getter("sprint.first_id"),
        set=_setter("sprint.first_id"),
    ),
    Setting(
        key="forecast.reference_capacity",
        label="Referenzkapazität (PT)",
        help="Darstellungsmaßstab der normierten Velocity (n. Velocity = Fokusfaktor × "
        "Referenzkapazität). Am besten die Kapazität eines voll besetzten Sprints. Sie kürzt "
        "sich in der Rechnung heraus: Ändert alle normierten Werte, aber nicht den Forecast "
        "PLAN.",
        kind=Kind.NUMBER,
        minimum=1,
        retroactive=True,
        get=_getter("forecast.reference_capacity"),
        set=_setter("forecast.reference_capacity", float),
    ),
    Setting(
        key="forecast.window",
        label="Ø über Sprints",
        help="Anzahl Sprints im gleitenden Durchschnitt. Kleiner = reagiert schneller, "
        "größer = ruhiger.",
        kind=Kind.INT,
        minimum=1,
        maximum=20,
        retroactive=True,
        get=_getter("forecast.window"),
        set=_setter("forecast.window", int),
    ),
    Setting(
        key="forecast.trend_mode",
        label="Trend-Modus",
        help="Wie der Durchschnitt in die Zukunft fortgeschrieben wird. „Konstant“ ist robust und "
        "der Standard. „Linear“ und „klassisch“ schreiben auch Rauschen fort: Sie können "
        "steigen oder fallen und sind nur bei einem belegten, stabilen Trend sinnvoll.",
        kind=Kind.CHOICE,
        choices={
            "flat": "letzter Durchschnitt bleibt konstant (Standard)",
            "classic": "linear, dann multiplikativ, dann linear (Vorsicht: schreibt Rauschen fort)",
            "linear": "durchgehend linear (Vorsicht: schreibt Rauschen fort)",
        },
        retroactive=True,
        get=lambda t: t.forecast.trend_mode.value,
        set=_setter("forecast.trend_mode", TrendMode),
    ),
    Setting(
        key="forecast.roadmap_share",
        label="Verplanbarer Anteil (%)",
        help="Anteil des Forecast PLAN, der für planbare Themen reserviert ist; der Rest ist "
        "„Kleinkram“.",
        kind=Kind.PERCENT,
        minimum=0,
        maximum=100,
        get=_getter("forecast.roadmap_share"),
        set=_setter("forecast.roadmap_share", float),
    ),
    Setting(
        key="forecast.horizon",
        label="Prognose-Horizont (Sprints)",
        help="Wie viele künftige Sprints in Prognose und Bericht erscheinen.",
        kind=Kind.INT,
        minimum=1,
        maximum=26,
        get=_getter("forecast.horizon"),
        set=_setter("forecast.horizon", int),
    ),
    Setting(
        key="forecast.rounding",
        label="Nachkommastellen Forecast PLAN",
        help=(
            "Der Forecast PLAN wird auf diese Stellen abgerundet: Er ist die Planungsmenge, und "
            "Abrunden schützt vor Überplanung. Die Kapazität dagegen wird intern ungerundet "
            "gerechnet und nur kaufmännisch gerundet angezeigt und gespeichert, damit der Nenner "
            "der normierten Velocity nicht systematisch zu klein wird."
        ),
        kind=Kind.INT,
        minimum=0,
        maximum=3,
        get=_getter("forecast.rounding"),
        set=_setter("forecast.rounding", int),
    ),
    Setting(
        key="forecast.product_basis",
        label="Standardverteilung je Produkt aus",
        help="Welche Menge gleichmäßig auf die betreuten Produkte verteilt wird "
        "(Standard = Menge / Anzahl Produkte).",
        kind=Kind.CHOICE,
        choices={
            "plan": "gesamter Forecast PLAN",
            "roadmap": "nur verplanbarer Anteil (Kleinkram bleibt produktübergreifend)",
        },
        get=lambda t: t.forecast.product_basis.value,
        set=_setter("forecast.product_basis", ProductBasis),
    ),
]

BY_KEY = {s.key: s for s in SETTINGS}
# Der erste Sprint wird beim Anlegen eines Teams zuerst gefragt (in dieser Reihenfolge).
FIRST_SPRINT_KEYS = ("sprint.numbering", "sprint.first_start", "sprint.first_id")
# Ländernamen bleiben unübersetzt (Eigennamen).
_COUNTRY = BY_KEY["capacity.country"]


def applicable(has_sprints: bool) -> list[Setting]:
    return [s for s in SETTINGS if not (s.only_without_sprints and has_sprints)]


def changes(before: Team, after: Team) -> list[tuple[Setting, str, str]]:
    """Geänderte Einstellungen als (Einstellung, alt, neu)."""
    return [
        (s, s.display(before), s.display(after))
        for s in SETTINGS
        if s.display(before) != s.display(after)
    ]
