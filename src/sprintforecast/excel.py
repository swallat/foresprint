# SPDX-License-Identifier: EUPL-1.2
"""Excel-Ausgabe eines Teams (Rückweg für Kolleginnen und Kollegen, die weiter mit einer
Excel-Liste arbeiten).

Die Mappe ist nicht mit einer früheren Liste identisch, rechnet aber dieselbe Logik wie
``engine.py`` mit echten Excel-Formeln: n. Velocity, gleitender Durchschnitt, Trend (nach dem
beim Export gültigen Trend-Modus), Kapazität, Forecast PLAN, Roadmap, Kleinkram, Fulfillment und
Fokusfaktor – dazu die Aufteilung nach Produktionszugriff und je Produkt und ein Liniendiagramm
des Trends. Die Formeln tragen den von der Engine berechneten Wert als Zwischenspeicher, damit
auch Vorschauprogramme Zahlen zeigen. Erfordert ``xlsxwriter`` (``sprintforecast[excel]``).
"""

from __future__ import annotations

import io
from collections.abc import Callable
from typing import Any

from sprintforecast.engine import MIN_THIN_HISTORY, Metric, parse_trend_mode, thin_history
from sprintforecast.forecast import Forecast, TimelineEntry
from sprintforecast.i18n import t
from sprintforecast.model import TrendMode
from sprintforecast.products import distribution, measure_label

NA = "#N/A"


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
    entries = [*fc.history(), *(e for e in fc.upcoming() if e not in fc.history())]
    if not entries:
        entries = list(fc.entries)
    unit = team.unit.value

    buf = io.BytesIO()
    wb = xw.Workbook(buf, {"in_memory": True, "nan_inf_to_errors": True})
    bold = wb.add_format({"bold": True, "text_wrap": True, "valign": "top", "bg_color": "#E8EEF7"})
    date_f = wb.add_format({"num_format": "dd.mm.yyyy"})
    n2 = wb.add_format({"num_format": "0.00"})
    n1 = wb.add_format({"num_format": "0.0"})
    pc = wb.add_format({"num_format": "0.0%"})
    inp = wb.add_format({"num_format": "0.00", "bg_color": "#FFF8DC"})
    inp1 = wb.add_format({"num_format": "0.0", "bg_color": "#FFF8DC"})
    grey = wb.add_format({"font_color": "#BBBBBB"})
    title = wb.add_format({"bold": True, "font_size": 14})

    ws_set = wb.add_worksheet(t("Einstellungen"))
    ws = wb.add_worksheet(t("Forecast"))
    ws_p = wb.add_worksheet(t("Produkte"))
    ws_t = wb.add_worksheet(t("Trend"))
    first, last = 3, 3 + len(entries) - 1  # Datenzeilen (0-basiert) auf dem Blatt „Forecast“

    # --- Einstellungen ------------------------------------------------------------------
    ws_set.write(0, 0, t("Einstellungen von {team}", team=team.name or team.key), title)
    rows = [
        (t("Referenzkapazität (PT)"), settings.reference_capacity, "Referenz"),
        (t("Fenster (Sprints)"), settings.window, "Fenster"),
        (t("Roadmap-Anteil"), settings.roadmap_share, "Roadmap_Anteil"),
        (t("Rundung (Nachkommastellen, abgerundet)"), settings.rounding, "Rundung"),
        (t("Trend-Modus (beim Export festgelegt)"), mode.value, None),
    ]
    for k, (label, value, name) in enumerate(rows, start=2):
        ws_set.write(k, 0, label)
        ws_set.write(k, 1, value, inp)
        if name:
            wb.define_name(name, f"='{ws_set.get_name()}'!$B${k + 1}")
    ws_set.write(8, 0, t("Stand"))
    ws_set.write(8, 1, f"{fc.today:%d.%m.%Y}")
    ws_set.write(
        13,
        0,
        t(
            "Gelbe Zellen sind Eingaben (Einstellungen und Sprintwerte); alle anderen Zellen sind "
            "Formeln. Der Trend-Modus ist in den Formeln fest gesetzt."
        ),
    )
    ws_set.set_column(0, 0, 48)
    ws_set.set_column(1, 1, 16)

    # --- Spalten des Blatts „Forecast“ -----------------------------------------------------
    cols = [
        "id", "start", "end", "ist", "vel", "scope", "cap", "src",
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
        "cap": t("Kapazität (PT), erfasst/berechnet"),
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
        "roadmap": t("Roadmap ({unit})", unit=unit),
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
        9, 0, t("Dünne Historie n. Velocity (weniger Werte als das Fenster, mindestens 3)")
    )
    ws_set.write_formula(9, 1, f"={thin_n}")
    ws_set.write(10 + 1, 0, t("Dünne Historie Kapazität"))
    ws_set.write_formula(11, 1, f"={thin_c}")
    wb.define_name("Duenn_nVelocity", f"='{ws_set.get_name()}'!$B$10")
    wb.define_name("Duenn_Kapazitaet", f"='{ws_set.get_name()}'!$B$12")

    # Zwischengespeicherte Werte: wie die Engine rechnet, damit Vorschauen Zahlen zeigen.
    values = [e.result for e in entries]
    norm_thin = thin_history([r.normalized_velocity.value for r in values], settings.window)
    cap_thin = thin_history([r.capacity.value for r in values], settings.window)
    ws_set.write_formula(9, 1, f"={thin_n}", None, norm_thin)
    ws_set.write_formula(11, 1, f"={thin_c}", None, cap_thin)

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
        for name, v, f in (
            ("ist", res.input.forecast_ist, inp),
            ("vel", res.input.velocity, inp),
            (
                "scope",
                res.input.scope_creep,
                wb.add_format({"num_format": "0.0%", "bg_color": "#FFF8DC"}),
            ),
            ("cap", res.input.capacity, inp1),
        ):
            if v is not None:
                ws.write_number(row, c[name], v, f)
            else:
                ws.write_blank(row, c[name], None, f)
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


def _products_sheet(
    wb: Any, ws_p: Any, ws: Any, c: dict[str, int], fc: Forecast, entries: list[TimelineEntry],
    first: int, last: int, bold: Any, n2: Any, unit: str,
) -> None:  # fmt: skip
    """Verteilung je Produkt (lange Tabelle) und Summe je Sprint zurück auf das Blatt Forecast."""
    team = fc.data.team
    production = team.features.production
    heads = [t("Sprint"), t("Produkt"), "PO", *(measure_label(m) + f" ({unit})" for m in
             ("standard", "preplanned", "planned", "done"))]  # fmt: skip
    if production:
        heads += [
            measure_label("production_planned") + f" ({unit})",
            measure_label("production_done") + f" ({unit})",
            t("Planning ohne Produktionszugriff ({unit})", unit=unit),
            t("Erledigt ohne Produktionszugriff ({unit})", unit=unit),
        ]
    for i, h in enumerate(heads):
        ws_p.write(0, i, h, bold)
    ws_p.set_row(0, 45)
    ws_p.set_column(0, 0, 10)
    ws_p.set_column(1, 2, 20)
    ws_p.set_column(3, len(heads), 15)
    ws_p.freeze_panes(1, 2)
    row = 1
    for e in entries:
        d = distribution(fc, e)
        for r in d.rows:
            if not (r.active or any(r.value(m) is not None for m in
                                    ("preplanned", "planned", "done"))):  # fmt: skip
                continue
            ws_p.write(row, 0, e.sprint.id)
            ws_p.write(row, 1, r.product.name)
            ws_p.write(row, 2, r.product.po or "")
            for k, m in enumerate(("standard", "preplanned", "planned", "done"), start=3):
                v = r.value(m)
                if v is not None:
                    ws_p.write_number(row, k, v, n2)
            if production:
                for k, m in ((7, "production_planned"), (8, "production_done")):
                    v = r.value(m)
                    if v is not None:
                        ws_p.write_number(row, k, v, n2)
                # F = Planning, G = Erledigt; H und I = davon mit Produktionszugriff
                for k, whole, part, a, b in (
                    (9, "F", "H", "planned", "production_planned"),
                    (10, "G", "I", "done", "production_done"),
                ):
                    w, p_ = f"{whole}{row + 1}", f"{part}{row + 1}"
                    va, vb = r.value(a), r.value(b)
                    ws_p.write_formula(
                        row, k, f'=IF(AND(ISNUMBER({w}),ISNUMBER({p_})),{w}-{p_},"")', n2,
                        "" if va is None or vb is None else va - vb,
                    )  # fmt: skip
            row += 1
    sheet = f"'{ws_p.get_name()}'!"
    last_row = max(row, 2)
    ids, plan_col = f"{sheet}$A$2:$A${last_row}", f"{sheet}$F$2:$F${last_row}"
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
