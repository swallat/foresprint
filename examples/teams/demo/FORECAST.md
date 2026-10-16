# Sprint-Forecast Demo-Team

Stand: 15.10.2026 · Einheit: PT · Referenzkapazität: 45 PT · Ø über 5 Sprints · Trend: `klassisch`

> Automatisch erzeugt mit `sprintforecast bericht`. Nicht von Hand bearbeiten.

## Prognose

| Sprint | Zeitraum | Status | Kapazität (PT) | n. Velocity-Trend | **Forecast PLAN** (PT) | Roadmap (80 %) | Kleinkram |
|---|---|---|---|---|---|---|---|
| 2026.21 | 14.10. – 28.10.2026 | **laufend** | 25,5 (Personenliste) | 16,02 | **9,0** | 7,20 | 1,80 |
| 2026.22 | 28.10. – 11.11.2026 | geplant | 30,0 (Personenliste) | 15,28 | **10,1** | 8,08 | 2,02 |
| 2026.23 | 11.11. – 25.11.2026 | geplant | 28,8 ⚠️ Trend | 14,53 | **9,2** | 7,36 | 1,84 |
| 2026.24 | 25.11. – 09.12.2026 | geplant | 28,4 ⚠️ Trend | 13,79 | **8,7** | 6,96 | 1,74 |

⚠️ *Trend*: Für diesen Sprint sind noch keine Fehltage erfasst, die Kapazität ist geschätzt. Mit `sprintforecast fehltage demo <SPRINT>` wird die Prognose belastbar.

**Planning 2026.21:** Summe 8,50 PT, Delta zum Forecast PLAN 0,50 PT

## Verlauf (letzte 10 Sprints)

| Sprint | Kapazität (PT) | Forecast IST | Velocity | n. Velocity | Ø n. Velocity | Fulfillment | Scope Creep |
|---|---|---|---|---|---|---|---|
| 2026.11 | 38,5 | 14,25 | 14,50 | 16,95 | 14,98 | 102 % | 20 % |
| 2026.12 | 32,1 | 11,75 | 13,50 | 18,93 | 16,46 | 115 % | 10 % |
| 2026.13 | 41,0 | 13,50 | 10,25 | 11,25 | 15,61 | 76 % | 0 % |
| 2026.14 | 35,4 | 13,25 | 12,50 | 15,89 | 15,55 | 94 % | 5 % |
| 2026.15 | 38,6 | 14,50 | 16,50 | 19,24 | 16,45 | 114 % | 5 % |
| 2026.16 | 34,0 | 13,25 | 14,00 | 18,53 | 16,77 | 106 % | 20 % |
| 2026.17 | 31,7 | 12,75 | 11,50 | 16,32 | 16,25 | 90 % | 0 % |
| 2026.18 | 28,5 | 10,00 | 10,50 | 16,58 | 17,31 | 105 % | 5 % |
| 2026.19 | 32,5 | 11,50 | 12,75 | 17,65 | 17,66 | 111 % | 0 % |
| 2026.20 | 29,0 | 12,00 | 9,75 | 15,13 | 16,84 | 81 % | 5 % |

## Diagramm

Linien: Forecast IST (Vergangenheit) bzw. Forecast PLAN (Zukunft), Velocity und normierte Velocity (Vergangenheit: Ist-Wert, Zukunft: Trend).

```mermaid
xychart-beta
    x-axis ["2026.11", "2026.12", "2026.13", "2026.14", "2026.15", "2026.16", "2026.17", "2026.18", "2026.19", "2026.20", "2026.21", "2026.22", "2026.23", "2026.24"]
    y-axis "PT"
    line [14.25, 11.75, 13.50, 13.25, 14.50, 13.25, 12.75, 10.00, 11.50, 12.00, 10.00, 10.10, 9.20, 8.70]
    line [14.50, 13.50, 10.25, 12.50, 16.50, 14.00, 11.50, 10.50, 12.75, 9.75, 10.35, 9.28, 8.21, 7.14]
    line [16.95, 18.93, 11.25, 15.89, 19.24, 18.53, 16.32, 16.58, 17.65, 15.13, 16.02, 15.28, 14.53, 13.79]
```

## Produkte

**Sprint 2026.21** (laufend)

| Produkt | PO | Standard (PT) | PO-Vorplanung (PT) | Planning (PT) | Erledigt (PT) |
|---|---|---|---|---|---|
| Webshop | Alex | 3,00 | 3,50 | 4,00 | – |
| Mobile App | Alex | 3,00 | 3,00 | 3,00 | – |
| Kundenportal | Bea | 3,00 | 3,00 | 3,00 | – |

**Sprint 2026.22** (geplant)

| Produkt | PO | Standard (PT) | PO-Vorplanung (PT) | Planning (PT) | Erledigt (PT) |
|---|---|---|---|---|---|
| Webshop | Alex | 3,37 | 3,00 | – | – |
| Mobile App | Alex | 3,37 | 3,00 | – | – |
| Kundenportal | Bea | 3,37 | 4,00 | – | – |

**Saldo** (Σ Erledigt − Σ Standard, letzte 6 Sprints)

| Produkt | Sprints | Σ Standard | Σ Erledigt | Saldo (PT) |
|---|---|---|---|---|
| Webshop | 4 | 14,57 | 16,50 | 1,93 |
| Mobile App | 4 | 14,57 | 14,75 | 0,18 |
| Kundenportal | 3 | 10,33 | 8,75 | -1,58 |
| Altsystem | 2 | 6,73 | 4,50 | -2,23 |

## Ergänzend: Bandbreite

Forecast mit der niedrigsten, mittleren und höchsten normierten Velocity der letzten 5 Sprints (statt des Trends).

| Sprint | Forecast PLAN (PT) | konservativ | mittel | optimistisch |
|---|---|---|---|---|
| 2026.21 | 9,0 | 8,5 | 9,3 | 10,5 |
| 2026.22 | 10,1 | 10,0 | 11,0 | 12,3 |
| 2026.23 | 9,2 | 9,6 | 10,5 | 11,8 |
| 2026.24 | 8,7 | 9,5 | 10,4 | 11,7 |

- Ø Fokusfaktor (Velocity / Kapazität): 0,37
- Ø Scope Creep (5 Sprints): 6 % · Kleinkram-Anteil: 20 %
