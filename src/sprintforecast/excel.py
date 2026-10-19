# SPDX-License-Identifier: EUPL-1.2
"""Excel-Ausgabe eines Teams (Rückweg für Kolleginnen und Kollegen, die weiter mit einer
Excel-Liste arbeiten).

Die Mappe ist nicht mit einer früheren Liste identisch, rechnet aber dieselbe Logik wie
``engine.py`` mit echten Excel-Formeln: n. Velocity, gleitender Durchschnitt, Trend (nach dem
beim Export gültigen Trend-Modus), Kapazität, Forecast PLAN, Verplanbar, Kleinkram, Fulfillment und
Fokusfaktor – dazu die Aufteilung nach Produktionszugriff und je Produkt und ein Liniendiagramm
des Trends. Die Formeln tragen den von der Engine berechneten Wert als Zwischenspeicher, damit
auch Vorschauprogramme Zahlen zeigen. Erfordert ``xlsxwriter`` (``sprintforecast[excel]``).
"""

from __future__ import annotations

import io
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from sprintforecast.engine import MIN_THIN_HISTORY, Metric, parse_trend_mode, thin_history
from sprintforecast.forecast import Forecast, TimelineEntry
from sprintforecast.i18n import t
from sprintforecast.model import TrendMode
from sprintforecast.products import distribution, measure_label
from sprintforecast.storage import TeamData, file_name_problem, team_to_dict

NA = "#N/A"

# Blattnamen und Aufbau sind fest (nicht übersetzt): Der Import erkennt die Mappe daran und liest
# die Eingaben nach Spaltenposition, nicht nach Überschrift. Bei Änderungen FORMAT_VERSION erhöhen.
FORMAT_VERSION = "1"
FORMAT_PROPERTY = "sprintforecast-format"
TEAM_PROPERTY = "sprintforecast-team"
SHEET_SETTINGS = "Einstellungen"
SHEET_FORECAST = "Forecast"
SHEET_SPRINTS = "Sprintdaten"
SHEET_ABSENCES = "Fehltage"
SHEET_PEOPLE = "Personen"
SHEET_PRODUCTS = "Produktliste"
SHEET_VALUES = "Produktwerte"
SHEET_PROGNOSES = "Prognosen"
SHEET_TREND = "Trend"
# Einstellungen: Spalte A Beschriftung, B Wert, C Schlüssel (Pfad in team.yaml, z. B.
# forecast.window).
SETTINGS_FIRST_ROW = 3
# Forecast: erste Datenzeile (0-basiert); Spalten 0-6 sind die Eingaben, die der Import liest.
FORECAST_FIRST_ROW = 3
# Sprintdaten (je Sprintdatei eine Zeile): fester Spaltenaufbau, Zeile 1 = Überschrift.
SPRINT_COLUMNS = (
    "id", "absence_state", "forecast_plan", "carryover", "backlog", "corrections",
    "not_done", "additional_done", "production_planned", "production_done", "note",
)  # fmt: skip
ABSENCE_COLUMNS = ("sprint", "person", "name", "days", "kind")
ABSENCE_KINDS = ("absences", "expected_absences")
PERSON_COLUMNS = (
    "id", "name", "country", "region", "workweek", "production_access", "from", "to", "fte",
)  # fmt: skip
PRODUCT_COLUMNS = ("id", "name", "po", "from", "to", "share")
VALUE_COLUMNS = (
    "sprint", "product", "name", "po", "standard",
    "preplanned", "planned", "done", "production_planned", "production_done",
)  # fmt: skip
PROGNOSIS_COLUMNS = (
    "sprint", "at", "comment", "forecast_ist", "not_done", "additional_done", "expected_done",
    "target", "plan", "preplanned",
)  # fmt: skip


def flatten(d: dict[str, Any], prefix: str = "") -> list[tuple[str, Any]]:
    """Verschachtelte Einstellungen als (Pfad, Wert); fehlende Werte (None) entfallen."""
    out: list[tuple[str, Any]] = []
    for key, value in d.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            out += flatten(value, path + ".")
        elif value is not None:
            out.append((path, value))
    return out


class ExcelUnavailable(RuntimeError):
    """``xlsxwriter`` ist nicht installiert."""


def _xlsxwriter() -> Any:
    try:
        import xlsxwriter
    except ImportError as e:
        raise ExcelUnavailable(
            t(
                "Die Excel-Ausgabe braucht xlsxwriter: sprintforecast mit dem Zusatz [excel] "
                "installieren."
            )
        ) from e
    return xlsxwriter


def import_unsafe_sprint_ids(data: TeamData) -> list[str]:
    """Warnings for sprint ids the Excel import would refuse (it requires portable file names).
    On Linux and macOS such an id (for example ``a:b``) can exist and be exported, but the
    workbook could not be imported again."""
    warnings = []
    seen: set[str] = set()
    ids = [s.id for s in data.sprints]
    if data.team.sprint.first_id is not None:
        ids.append(data.team.sprint.first_id)
    for index, sprint_id in enumerate(ids):
        is_first_id = index >= len(data.sprints)
        if problem := file_name_problem(sprint_id):
            warnings.append(
                t(
                    "Sprint-ID {id} ({problem}): Der Excel-Import lehnt sie ab; "
                    "die Datei lässt sich nicht wieder importieren.",
                    id=repr(sprint_id),
                    problem=problem,
                )
            )
        elif not is_first_id and sprint_id.casefold() in seen:
            warnings.append(
                t(
                    "Sprint-ID {id} kommt zweimal vor (Groß- und Kleinschreibung zählt "
                    "gleich): Der Excel-Import lehnt das ab.",
                    id=repr(sprint_id),
                )
            )
        if not is_first_id:
            seen.add(sprint_id.casefold())
    return warnings


def _blank(value: float | None) -> float | str:
    return "" if value is None else value


def _cell(col: int, row: int, abs_col: bool = False, abs_row: bool = False) -> str:
    from xlsxwriter.utility import xl_rowcol_to_cell

    return xl_rowcol_to_cell(row, col, row_abs=abs_row, col_abs=abs_col)


def _num(ref: str) -> str:
    return f"ISNUMBER({ref})"


def _known(ref_avg: str, ref_trend: str) -> str:
    return f'IF(ISNUMBER({ref_avg}),{ref_avg},IF(ISNUMBER({ref_trend}),{ref_trend},""))'


def trend_formula(mode: TrendMode, thin_ref: str, r: Callable[[str, int], str], i: int) -> str:
    """Excel-Formel der Fortschreibung für Zeile ``i`` (0 = erster Sprint); spiegelt
    ``engine._trend``. ``r(spalte, offset)`` liefert den Zellbezug ``spalte`` in Zeile ``i-offset``
    (``''`` vor dem ersten Sprint). Nur wo der Durchschnitt fehlt."""

    def has(col: str, off: int) -> bool:
        return i - off >= 0

    def ref(col: str, off: int) -> str:
        return r(col, off) if has(col, off) else '""'

    k1 = f"{ref('known', 1)}"
    k2 = f"{ref('known', 2)}"
    fallback = f'IF({_num(k1)},{k1},"")' if has("known", 1) else '""'
    flat = fallback
    if has("known", 2):
        linear = f"IF(AND({_num(k1)},{_num(k2)}),MAX(0,{k1}+({k1}-{k2})),{fallback})"
    else:
        linear = fallback
    if mode is TrendMode.FLAT:
        body = flat
    elif mode is TrendMode.LINEAR:
        body = linear
    else:  # classic
        a1, a2, a3 = ref("avg", 1), ref("avg", 2), ref("avg", 3)
        t1, t2 = ref("trend", 1), ref("trend", 2)
        parts = linear
        if i >= 2:
            ratio = f"{a2}/{a3}*{t1}" if has("avg", 3) else '""'
            ratio_branch = (
                f"IF(AND({_num(a2)},{_num(a3)},{_num(t1)}),MAX(0,{ratio}),{fallback})"
                if has("avg", 3)
                else fallback
            )
            parts = f"IF({_num(t2)},{linear},{ratio_branch})"
        if i >= 1:
            body = (
                f"IF({_num(a1)},IF({_num(a2)},MAX(0,{a1}+({a1}-{a2})),{fallback}),{parts})"
                if has("avg", 2)
                else f"IF({_num(a1)},{fallback},{parts})"
            )
        else:
            body = parts
    return f"IF({thin_ref},{flat},{body})"


def build_workbook(fc: Forecast) -> bytes:
    """Die Excel-Mappe des Teams als Bytes (``.xlsx``)."""
    xw = _xlsxwriter()
    data = fc.data
    team = data.team
    settings = team.forecast
    mode = parse_trend_mode(settings.trend_mode)
    entries = list(fc.entries)  # alle Sprints: die Mappe enthält die Historie vollständig
    unit = team.unit.value

    buf = io.BytesIO()
    wb = xw.Workbook(
        buf,
        {
            "in_memory": True,
            "nan_inf_to_errors": True,
            # Importierte Texte (Notizen, Namen) beginnen vielleicht mit "=": als Text schreiben.
            "strings_to_formulas": False,
            "strings_to_urls": False,
        },
    )
    bold = wb.add_format({"bold": True, "text_wrap": True, "valign": "top", "bg_color": "#E8EEF7"})
    date_f = wb.add_format({"num_format": "dd.mm.yyyy"})
    n2 = wb.add_format({"num_format": "0.00"})
    n1 = wb.add_format({"num_format": "0.0"})
    pc = wb.add_format({"num_format": "0.0%"})
    inp = wb.add_format({"num_format": "0.00", "bg_color": "#FFF8DC"})
    inp1 = wb.add_format({"num_format": "0.0", "bg_color": "#FFF8DC"})
    set_f = wb.add_format({"bg_color": "#FFF8DC"})
    scope_f = wb.add_format({"num_format": "0.0%", "bg_color": "#FFF8DC"})
    grey = wb.add_format({"font_color": "#BBBBBB"})
    title = wb.add_format({"bold": True, "font_size": 14})

    wb.set_custom_property(FORMAT_PROPERTY, FORMAT_VERSION)
    wb.set_custom_property(TEAM_PROPERTY, team.key)
    ws_set = wb.add_worksheet(SHEET_SETTINGS)
    ws = wb.add_worksheet(SHEET_FORECAST)
    ws_sp = wb.add_worksheet(SHEET_SPRINTS)
    ws_a = wb.add_worksheet(SHEET_ABSENCES)
    ws_pe = wb.add_worksheet(SHEET_PEOPLE)
    ws_pr = wb.add_worksheet(SHEET_PRODUCTS)
    ws_p = wb.add_worksheet(SHEET_VALUES)
    ws_pg = wb.add_worksheet(SHEET_PROGNOSES)
    ws_t = wb.add_worksheet(SHEET_TREND)
    first, last = (
        FORECAST_FIRST_ROW,
        FORECAST_FIRST_ROW + len(entries) - 1,
    )  # Datenzeilen (0-basiert) auf dem Blatt „Forecast“

    # --- Einstellungen ------------------------------------------------------------------
    ws_set.write(0, 0, t("Einstellungen von {team}", team=team.name or team.key), title)
    ws_set.write(1, 0, t("Beschriftung"), bold)
    ws_set.write(1, 1, t("Wert"), bold)
    ws_set.write(1, 2, t("Schlüssel (team.yaml)"), bold)
    labels = {
        "forecast.reference_capacity": t("Referenzkapazität (PT)"),
        "forecast.window": t("Fenster (Sprints)"),
        "forecast.roadmap_share": t("Verplanbarer Anteil"),
        "forecast.rounding": t("Rundung (Nachkommastellen, abgerundet)"),
        "forecast.trend_mode": t("Trend-Modus (beim Export festgelegt)"),
    }
    names = {
        "forecast.reference_capacity": "Referenz",
        "forecast.window": "Fenster",
        "forecast.roadmap_share": "Roadmap_Anteil",
        "forecast.rounding": "Rundung",
    }
    # The tracker section (ticket pre-planning) is not a spreadsheet setting: the import keeps
    # the existing section of team.yaml.
    flat = [(p, v) for p, v in flatten(team_to_dict(team)) if not p.startswith("tracker.")]
    for k, (path, value) in enumerate(flat, start=SETTINGS_FIRST_ROW - 1):
        ws_set.write(k, 0, labels.get(path, path))
        if isinstance(value, date):
            ws_set.write_datetime(k, 1, _dt(value), wb.add_format({"num_format": "dd.mm.yyyy"}))
        else:
            ws_set.write(k, 1, value, set_f)
        ws_set.write(k, 2, path, grey)
        if path in names:
            wb.define_name(names[path], f"='{ws_set.get_name()}'!$B${k + 1}")
    thin_row = SETTINGS_FIRST_ROW - 1 + len(flat) + 1
    ws_set.write(thin_row + 3, 0, t("Stand"))
    ws_set.write(thin_row + 3, 1, f"{fc.today:%d.%m.%Y}")
    ws_set.write(
        thin_row + 5,
        0,
        t(
            "Gelbe Zellen sind Eingaben (Einstellungen und Sprintwerte); alle anderen Zellen sind "
            "Formeln. Der Trend-Modus ist in den Formeln fest gesetzt."
        ),
    )
    ws_set.set_column(0, 0, 48)
    ws_set.set_column(1, 1, 16)
    ws_set.set_column(2, 2, 30)

    # --- Spalten des Blatts „Forecast“ -----------------------------------------------------
    cols = [
        "id", "start", "end", "ist", "vel", "scope", "caprec", "capcalc", "src", "cap",
        "norm", "norm_n", "norm_avg", "norm_trend", "norm_known",
        "cap_n", "cap_avg", "cap_trend", "cap_known",
        "plancap", "plan", "roadmap", "small", "ful", "focus",
        "share", "capprod", "capnon", "planprod", "plannon", "sumprod", "delta",
    ]  # fmt: skip
    c = {name: i for i, name in enumerate(cols)}
    headers = {
        "id": t("Sprint"),
        "start": t("Start"),
        "end": t("Ende"),
        "ist": t("Commitment ({unit})", unit=unit),
        "vel": t("Velocity ({unit})", unit=unit),
        "scope": t("Scope Creep"),
        "caprec": t("Kapazität (PT), erfasst (Eingabe)"),
        "capcalc": t("Kapazität (PT), aus Personen und Kalender berechnet"),
        "cap": t("Kapazität (PT), erfasst oder berechnet"),
        "src": t("Quelle der Kapazität"),
        "norm": t("n. Velocity"),
        "norm_n": t("Anzahl n. Velocity"),
        "norm_avg": t("Ø n. Velocity"),
        "norm_trend": t("n. Velocity-Trend"),
        "norm_known": t("n. Velocity bekannt (Ø oder Trend)"),
        "cap_n": t("Anzahl Kapazität"),
        "cap_avg": t("Ø Kapazität"),
        "cap_trend": t("Kapazität-Trend"),
        "cap_known": t("Kapazität bekannt (Ø oder Trend)"),
        "plancap": t("Kapazität für den Forecast PLAN (PT)"),
        "plan": t("Forecast PLAN ({unit})", unit=unit),
        "roadmap": t("Verplanbar ({unit})", unit=unit),
        "small": t("Kleinkram ({unit})", unit=unit),
        "ful": t("Fulfillment"),
        "focus": t("Fokusfaktor"),
        "share": t("Anteil Produktionszugriff an der Kapazität"),
        "capprod": t("Kapazität mit Produktionszugriff (PT)"),
        "capnon": t("Kapazität ohne Produktionszugriff (PT)"),
        "planprod": t("Forecast PLAN: bis zu mit Produktionszugriff ({unit})", unit=unit),
        "plannon": t("Forecast PLAN: für alle übrigen ({unit})", unit=unit),
        "sumprod": t("Σ Planning je Produkt ({unit})", unit=unit),
        "delta": t("Forecast PLAN − Σ Planning ({unit})", unit=unit),
    }
    ws.write(0, 0, t("Forecast {team}", team=team.name or team.key), title)
    ws.write(
        1,
        0,
        t("Eingaben gelb; die Spalten rechts davon rechnen wie die Weboberfläche (Rechenweg)."),
    )
    for name, i in c.items():
        ws.write(2, i, headers[name], bold)
    ws.set_row(2, 60)
    ws.set_column(0, 0, 10)
    ws.set_column(1, 2, 11)
    ws.set_column(3, len(cols), 14)
    ws.freeze_panes(3, 1)

    def at(name: str, row: int, ca: bool = False, ra: bool = False) -> str:
        return _cell(c[name], row, abs_col=ca, abs_row=ra)

    def rng(name: str, a: int, b: int) -> str:
        return f"{at(name, a, True, True)}:{at(name, b, True, True)}"

    norm_all = rng("norm", first, last)
    # Dünne Historie je Reihe (zu wenige Werte für ein volles Fenster, aber ≥ 3).
    sheet = f"'{ws.get_name()}'!"
    thin_n = f"AND(COUNT({sheet}{norm_all})>={MIN_THIN_HISTORY},COUNT({sheet}{norm_all})<Fenster)"
    thin_c = (
        f"AND(COUNT({sheet}{rng('cap', first, last)})>={MIN_THIN_HISTORY},"
        f"COUNT({sheet}{rng('cap', first, last)})<Fenster)"
    )
    ws_set.write(
        thin_row, 0, t("Dünne Historie n. Velocity (weniger Werte als das Fenster, mindestens 3)")
    )
    ws_set.write(thin_row + 1, 0, t("Dünne Historie Kapazität"))
    wb.define_name("Duenn_nVelocity", f"='{ws_set.get_name()}'!$B${thin_row + 1}")
    wb.define_name("Duenn_Kapazitaet", f"='{ws_set.get_name()}'!$B${thin_row + 2}")

    # Zwischengespeicherte Werte: wie die Engine rechnet, damit Vorschauen Zahlen zeigen.
    values = [e.result for e in entries]
    norm_thin = thin_history([r.normalized_velocity.value for r in values], settings.window)
    cap_thin = thin_history([r.capacity.value for r in values], settings.window)
    ws_set.write_formula(thin_row, 1, f"={thin_n}", None, norm_thin)
    ws_set.write_formula(thin_row + 1, 1, f"={thin_c}", None, cap_thin)

    def series_columns(
        i: int,
        row: int,
        prefix: str,
        valname: str,
        m: Metric,
        count: int,
        thin: str,
        thin_name: str,
    ) -> None:
        n_c, avg_c, tr_c, kn_c = (f"{prefix}_{x}" for x in ("n", "avg", "trend", "known"))
        ws.write_formula(
            row,
            c[n_c],
            f"=COUNT({at(valname, first, False, True)}:{at(valname, row)})",
            None,
            count,
        )
        cnt = at(n_c, row)
        val = at(valname, row)
        window_avg = (
            f"AVERAGEIFS({at(valname, first, False, True)}:{at(valname, row)},"
            f'{at(n_c, first, False, True)}:{cnt},">"&({cnt}-Fenster))'
        )
        thin_avg = f"AVERAGE({at(valname, first, False, True)}:{at(valname, row)})"
        ws.write_formula(
            row,
            c[avg_c],
            f'=IF(NOT({_num(val)}),"",IF({cnt}>=Fenster,{window_avg},'
            f'IF(AND({thin_name},{cnt}>={MIN_THIN_HISTORY}),{thin_avg},"")))',
            n2,
            _blank(m.average),
        )

        def r(col: str, off: int) -> str:
            return at(f"{prefix}_{col}", row - off)

        body = trend_formula(mode, thin_name, r, i)
        ws.write_formula(
            row,
            c[tr_c],
            f'=IF({_num(at(avg_c, row))},"",{body})',
            n2,
            _blank(m.trend if m.average is None else None),
        )
        ws.write_formula(
            row,
            c[kn_c],
            "=" + _known(at(avg_c, row), at(tr_c, row)),
            n2,
            _blank(m.average if m.average is not None else m.trend),
        )

    n_count = cap_count = 0
    for i, e in enumerate(entries):
        row = first + i
        res = e.result
        s = e.sprint
        ws.write(row, c["id"], s.id)
        ws.write_datetime(row, c["start"], _dt(s.start), date_f)
        ws.write_datetime(row, c["end"], _dt(s.end), date_f)
        # Eingaben (gelb): genau die Felder der Sprintdatei; fehlt ein Wert, bleibt die Zelle leer.
        for name, v, f in (
            ("ist", s.forecast_ist, inp),
            ("vel", s.velocity, inp),
            ("scope", s.scope_creep, scope_f),
            ("caprec", s.capacity, inp1),
        ):
            if v is not None:
                ws.write_number(row, c[name], v, f)
            else:
                ws.write_blank(row, c[name], None, f)
        calc = res.input.capacity if s.capacity is None else None
        if calc is not None:
            ws.write_number(row, c["capcalc"], calc, n1)
        ws.write_formula(
            row,
            c["cap"],
            f"=IF({_num(at('caprec', row))},{at('caprec', row)},"
            f'IF({_num(at("capcalc", row))},{at("capcalc", row)},""))',
            n1,
            _blank(res.input.capacity),
        )
        ws.write(
            row, c["src"], res.input.capacity_source.value if res.input.capacity_source else ""
        )
        nv = res.normalized_velocity
        ws.write_formula(
            row,
            c["norm"],
            f"=IF(AND({_num(at('vel', row))},{_num(at('cap', row))},{at('cap', row)}>0),"
            f'{at("vel", row)}/{at("cap", row)}*Referenz,"")',
            n2,
            _blank(nv.value),
        )
        n_count += nv.value is not None
        cap_count += res.capacity.value is not None
        series_columns(i, row, "norm", "norm", nv, n_count, "norm", "Duenn_nVelocity")
        series_columns(i, row, "cap", "cap", res.capacity, cap_count, "cap", "Duenn_Kapazitaet")
        ws.write_formula(
            row,
            c["plancap"],
            f"=IF({_num(at('cap', row))},{at('cap', row)},{at('cap_trend', row)})",
            n1,
            _blank(res.plan_capacity),
        )
        tr, pcap, ist = at("norm_trend", row), at("plancap", row), at("ist", row)
        ws.write_formula(
            row,
            c["plan"],
            f"=IF(AND({_num(tr)},{_num(pcap)}),MAX(0,ROUNDDOWN({tr}/Referenz*{pcap},Rundung)),"
            f'IF({_num(ist)},ROUNDDOWN({ist},Rundung),""))',
            n2,
            _blank(res.plan),
        )
        plan = at("plan", row)
        ws.write_formula(
            row,
            c["roadmap"],
            f'=IF({_num(plan)},{plan}*Roadmap_Anteil,"")',
            n2,
            _blank(res.roadmap),
        )
        ws.write_formula(
            row,
            c["small"],
            f'=IF({_num(plan)},{plan}-{at("roadmap", row)},"")',
            n2,
            _blank(res.small_stuff),
        )
        vel, cap = at("vel", row), at("cap", row)
        ws.write_formula(
            row,
            c["ful"],
            f'=IF(AND({_num(vel)},{_num(ist)},{ist}<>0),{vel}/{ist},"")',
            pc,
            _blank(res.fulfillment.value),
        )
        focus = (
            res.input.velocity / res.input.capacity
            if res.input.velocity is not None and res.input.capacity
            else None
        )
        ws.write_formula(
            row,
            c["focus"],
            f'=IF(AND({_num(vel)},{_num(cap)},{cap}>0),{vel}/{cap},"")',
            pc,
            _blank(focus),
        )
        _production_columns(ws, c, at, row, fc, e, res, n1, n2, pc)

    _data_sheets(wb, fc, entries, (ws_sp, ws_a, ws_pe, ws_pr, ws_pg), bold, inp, date_f)
    _products_sheet(wb, ws_p, ws, c, fc, entries, first, last, bold, n2, unit)
    _trend_sheet(wb, ws_t, ws, c, entries, first, bold, grey)
    wb.close()
    return buf.getvalue()


def _dt(d: Any) -> Any:
    from datetime import datetime

    return datetime(d.year, d.month, d.day)


def _production_columns(
    ws: Any, c: dict[str, int], at: Callable[..., str], row: int, fc: Forecast,
    e: TimelineEntry, res: Any, n1: Any, n2: Any, pc: Any,
) -> None:  # fmt: skip
    """Aufteilung nach Produktionszugriff (Näherung über den Kapazitätsanteil)."""
    d = distribution(fc, e) if fc.data.team.features.production else None
    share = d.production_share if d is not None and d.production_state == "ok" else None
    if share is None:
        return
    ws.write_number(row, c["share"], share, pc)
    share_ref, pcap, plan = at("share", row), at("plancap", row), at("plan", row)
    cap = res.plan_capacity
    ws.write_formula(
        row, c["capprod"], f'=IF({_num(pcap)},{pcap}*{share_ref},"")', n1,
        _blank(None if cap is None else cap * share),
    )  # fmt: skip
    ws.write_formula(
        row, c["capnon"], f'=IF({_num(pcap)},{pcap}*(1-{share_ref}),"")', n1,
        _blank(None if cap is None else cap * (1 - share)),
    )  # fmt: skip
    ws.write_formula(
        row, c["planprod"], f'=IF({_num(plan)},{plan}*{share_ref},"")', n2,
        _blank(None if res.plan is None else res.plan * share),
    )  # fmt: skip
    ws.write_formula(
        row, c["plannon"], f'=IF({_num(plan)},{plan}*(1-{share_ref}),"")', n2,
        _blank(None if res.plan is None else res.plan * (1 - share)),
    )  # fmt: skip


def _header(ws: Any, labels: list[str], bold: Any, widths: list[int] | None = None) -> None:
    for i, label in enumerate(labels):
        ws.write(0, i, label, bold)
    ws.set_row(0, 45)
    for i, width in enumerate(widths or []):
        ws.set_column(i, i, width)
    ws.freeze_panes(1, 0)


def _put(ws: Any, row: int, col: int, value: Any, fmt: Any = None) -> None:
    """Schreibt einen Wert; ``None`` bleibt eine leere Zelle (mit Format, damit sie gelb ist)."""
    if value is None:
        ws.write_blank(row, col, None, fmt)
    elif isinstance(value, datetime):
        ws.write_datetime(row, col, value.replace(tzinfo=None), fmt)
    elif isinstance(value, date):
        ws.write_datetime(row, col, _dt(value), fmt)
    else:
        ws.write(row, col, value, fmt)


def _data_sheets(
    wb: Any, fc: Forecast, entries: list[TimelineEntry], sheets: tuple[Any, ...],
    bold: Any, inp: Any, date_f: Any,
) -> None:  # fmt: skip
    """Die übrigen Daten des Teams (Sprintdateien, Fehltage, Personen, Produkte, Prognosen) in
    der festen Spaltenfolge, die der Import liest. Alles Eingaben (gelb) außer den Namen."""
    ws_sp, ws_a, ws_pe, ws_pr, ws_pg = sheets
    data = fc.data
    unit = data.team.unit.value
    inp_date = wb.add_format({"num_format": "dd.mm.yyyy", "bg_color": "#FFF8DC"})
    inp_time = wb.add_format({"num_format": "dd.mm.yyyy hh:mm:ss", "bg_color": "#FFF8DC"})
    inp_text = wb.add_format({"bg_color": "#FFF8DC"})
    names = {p.id: p.name for p in data.people}
    recorded = [e.sprint for e in entries if e.recorded]

    _header(
        ws_sp,
        [
            t("Sprint"), t("Stand der Fehltage (unknown, expected, confirmed)"),
            t("Forecast PLAN beim Planning, eingefroren ({unit})", unit=unit),
            t("Überkipper ({unit})", unit=unit), f"Backlog ({unit})",
            t("Korrekturen Restaufwände (mit Leerzeichen getrennt)"),
            t("Davon nicht erledigt ({unit})", unit=unit),
            t("Zusätzlich erledigt ({unit})", unit=unit),
            t("Davon mit Produktionszugriff, Planning ({unit})", unit=unit),
            t("Davon mit Produktionszugriff, erledigt ({unit})", unit=unit),
            t("Notiz"),
        ],
        bold,
        [10, 22, 18, 14, 12, 26, 16, 16, 20, 20, 40],
    )  # fmt: skip
    for row, sp in enumerate(recorded, start=1):
        pl = sp.planning
        values = [
            sp.id, sp.absence_state.value if sp.absence_state else None, sp.forecast_plan,
            pl.carryover if pl else None, pl.backlog if pl else None,
            " ".join(f"{x:g}" for x in pl.corrections) if pl and pl.corrections else None,
            sp.not_done, sp.additional_done, sp.production_planned, sp.production_done, sp.note,
        ]  # fmt: skip
        for col, v in enumerate(values):
            _put(ws_sp, row, col, v, None if col == 0 else inp_text if col in (1, 5, 10) else inp)

    _header(
        ws_a,
        [
            t("Sprint"), t("Person (Kennung)"), t("Name"), t("Tage"),
            t("Art (absences = bestätigt, expected_absences = angekündigt)"),
        ],
        bold,
        [10, 20, 24, 8, 30],
    )  # fmt: skip
    row = 1
    for sp in recorded:
        for kind, days in (("absences", sp.absences), ("expected_absences", sp.expected_absences)):
            for pid, value in sorted(days.items()):
                for col, v in enumerate([sp.id, pid, names.get(pid, ""), value, kind]):
                    _put(ws_a, row, col, v, inp if col == 3 else None)
                row += 1

    _header(
        ws_pe,
        [
            t("Kennung"), t("Name"), t("Land"), t("Region"), t("Arbeitswoche"),
            t("Produktionszugriff"), t("Mitglied ab"), t("Mitglied bis"), "FTE",
        ],
        bold,
        [16, 24, 8, 8, 18, 12, 13, 13, 8],
    )  # fmt: skip
    row = 1
    for person in data.people:
        for m in person.memberships or [None]:
            values = [
                person.id, person.name, person.country, person.region, person.workweek,
                True if person.production_access else None,
                m.start if m else None, m.end if m else None, m.fte if m else None,
            ]  # fmt: skip
            for col, v in enumerate(values):
                fmt = inp_date if col in (6, 7) else inp if col == 8 else inp_text
                _put(ws_pe, row, col, v, fmt)
            row += 1

    _header(
        ws_pr,
        [
            t("Kennung"), t("Name"), "PO", t("Betreut ab"), t("Betreut bis"),
            t("Fester Anteil (0–1)"),
        ],
        bold,
        [16, 24, 18, 13, 13, 12],
    )  # fmt: skip
    for row, p in enumerate(data.products, start=1):
        values = [p.id, p.name, p.po, p.start, p.end, p.share]
        for col, v in enumerate(values):
            _put(ws_pr, row, col, v, inp_date if col in (3, 4) else inp if col == 5 else inp_text)

    _header(
        ws_pg,
        [
            t("Sprint"), t("Zeitpunkt"), t("Kommentar"), t("Commitment ({unit})", unit=unit),
            t("Voraussichtlich nicht erledigt ({unit})", unit=unit),
            t("Zusätzlich erledigt ({unit})", unit=unit), t("Erwartet erledigt"),
            t("Zielsprint"), t("Forecast PLAN"), t("Vorplanung je Produkt (Kennung=Wert; …)"),
        ],
        bold,
        [10, 19, 40, 12, 14, 14, 12, 10, 12, 40],
    )  # fmt: skip
    row = 1
    for sp in recorded:
        for pg in sp.prognoses:
            pre = "; ".join(f"{k}={v:g}" for k, v in pg.preplanned.items()) or None
            values = [
                sp.id, pg.at, pg.comment, pg.forecast_ist, pg.not_done, pg.additional_done,
                pg.expected_done, pg.target, pg.plan, pre,
            ]  # fmt: skip
            for col, v in enumerate(values):
                fmt = (
                    None if col == 0 else inp_time if col == 1
                    else inp if col in (3, 4, 5, 6, 8) else inp_text
                )  # fmt: skip
                _put(ws_pg, row, col, v, fmt)
            row += 1


def _products_sheet(
    wb: Any, ws_p: Any, ws: Any, c: dict[str, int], fc: Forecast, entries: list[TimelineEntry],
    first: int, last: int, bold: Any, n2: Any, unit: str,
) -> None:  # fmt: skip
    """Werte je Produkt und Sprint (lange Tabelle, feste Spalten wie ``VALUE_COLUMNS``) und die
    Summe je Sprint zurück auf das Blatt Forecast."""
    production = fc.data.team.features.production
    inp = wb.add_format({"num_format": "0.00", "bg_color": "#FFF8DC"})
    _header(
        ws_p,
        [
            t("Sprint"), t("Produkt (Kennung)"), t("Produkt"), "PO",
            *(
                measure_label(m) + f" ({unit})"
                for m in ("standard", "preplanned", "planned", "done")
            ),
            measure_label("production_planned") + f" ({unit})",
            measure_label("production_done") + f" ({unit})",
            t("Planning ohne Produktionszugriff ({unit})", unit=unit),
            t("Erledigt ohne Produktionszugriff ({unit})", unit=unit),
        ],
        bold,
        [10, 16, 22, 16, 12, 12, 12, 12, 14, 14, 16, 16],
    )  # fmt: skip
    measures = ("preplanned", "planned", "done", "production_planned", "production_done")
    row = 1
    for e in entries:
        d = distribution(fc, e)
        for r in d.rows:
            if not (r.active or any(r.value(m) is not None for m in measures)):
                continue
            for col, v in enumerate([e.sprint.id, r.product.id, r.product.name, r.product.po]):
                ws_p.write(row, col, v or "")
            if r.standard is not None:
                ws_p.write_number(row, 4, r.standard, n2)
            for col, m in enumerate(measures, start=5):
                _put(ws_p, row, col, r.value(m), inp)
            if production:
                for col, whole, part, a, b in (
                    (10, "G", "I", "planned", "production_planned"),
                    (11, "H", "J", "done", "production_done"),
                ):
                    w, p_ = f"{whole}{row + 1}", f"{part}{row + 1}"
                    va, vb = r.value(a), r.value(b)
                    ws_p.write_formula(
                        row, col, f'=IF(AND(ISNUMBER({w}),ISNUMBER({p_})),{w}-{p_},"")', n2,
                        "" if va is None or vb is None else va - vb,
                    )  # fmt: skip
            row += 1
    sheet = f"'{ws_p.get_name()}'!"
    last_row = max(row, 2)
    ids, plan_col = f"{sheet}$A$2:$A${last_row}", f"{sheet}$G$2:$G${last_row}"
    for i, e in enumerate(entries):
        r_ = first + i
        d = distribution(fc, e)
        total = d.total("planned")
        ws.write_formula(
            r_, c["sumprod"],
            f'=IF(COUNTIFS({ids},{_cell(c["id"], r_)},{plan_col},"<>")=0,"",'
            f'SUMIFS({plan_col},{ids},{_cell(c["id"], r_)}))',
            n2, _blank(total),
        )  # fmt: skip
        plan = _cell(c["plan"], r_)
        sums = _cell(c["sumprod"], r_)
        ws.write_formula(
            r_, c["delta"], f'=IF(AND(ISNUMBER({plan}),ISNUMBER({sums})),{plan}-{sums},"")', n2,
            _blank(None if total is None or e.result.plan is None else e.result.plan - total),
        )  # fmt: skip


def _trend_sheet(
    wb: Any, ws_t: Any, ws: Any, c: dict[str, int], entries: list[TimelineEntry], first: int,
    bold: Any, grey: Any,
) -> None:  # fmt: skip
    """Diagrammdaten (``#NV`` = Lücke) und zwei Liniendiagramme: Trend der normierten Velocity,
    Forecast PLAN gegen Velocity und Commitment."""
    sheet = f"'{ws.get_name()}'!"
    heads = [
        t("Sprint"), t("n. Velocity"), t("Ø n. Velocity"), t("n. Velocity-Trend"),
        t("Forecast PLAN"), t("Velocity"), t("Commitment"),
    ]  # fmt: skip
    for i, h in enumerate(heads):
        ws_t.write(0, i, h, bold)
    ws_t.set_column(0, 6, 16)
    sources = ["id", "norm", "norm_avg", "norm_trend", "plan", "vel", "ist"]
    cached = [
        lambda e: e.sprint.id,
        lambda e: e.result.normalized_velocity.value,
        lambda e: e.result.normalized_velocity.average,
        lambda e: e.result.normalized_velocity.trend,
        lambda e: e.result.plan,
        lambda e: e.result.input.velocity,
        lambda e: e.result.input.forecast_ist,
    ]
    for i, e in enumerate(entries):
        for k, (src, get) in enumerate(zip(sources, cached, strict=True)):
            ref = f"{sheet}{_cell(c[src], first + i)}"
            if k == 0:
                ws_t.write_formula(i + 1, 0, f"={ref}", None, e.sprint.id)
            else:
                v = get(e)
                ws_t.write_formula(
                    i + 1, k, f"=IF(ISNUMBER({ref}),{ref},NA())", None, NA if v is None else v
                )
    last = len(entries)
    ws_t.conditional_format(1, 1, last, 6, {"type": "errors", "format": grey})
    tname = f"'{ws_t.get_name()}'!"

    def chart(chart_title: str, columns: list[int], anchor: str, ytitle: str) -> None:
        ch = wb.add_chart({"type": "line"})
        for col in columns:
            ch.add_series(
                {
                    "name": f"={tname}{_cell(col, 0, True, True)}",
                    "categories": f"={tname}$A$2:$A${last + 1}",
                    "values": f"={tname}{_cell(col, 1, True, True)}:{_cell(col, last, True, True)}",
                    "marker": {"type": "circle", "size": 5},
                    "line": {"width": 2},
                }
            )
        ch.set_title({"name": chart_title})
        ch.set_y_axis({"name": ytitle, "major_gridlines": {"visible": True}})
        ch.set_x_axis({"name": t("Sprint")})
        ch.set_legend({"position": "bottom"})
        ch.show_na_as_empty_cell()
        ch.show_blanks_as("gap")
        ch.set_size({"width": 760, "height": 340})
        ws_t.insert_chart(anchor, ch)

    chart(t("Trend der normierten Velocity"), [1, 2, 3], "I2", t("n. Velocity"))
    chart(t("Forecast PLAN, Velocity und Commitment"), [4, 5, 6], "I20", t("Menge"))
