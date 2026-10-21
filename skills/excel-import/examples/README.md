# Worked example

`demo-sheet/` is an invented workbook, shown as one CSV per sheet (semicolon-separated, German
dates, decimal comma where relevant): team data, people, products and a sprint log.
`expected/teams/sheet-demo/` is what a correct import produces.

Decisions the importer had to make (and would have asked about):

| Sheet fact | Question | Result |
|---|---|---|
| "Estimation unit: Story points" | confirmed unit | `unit: SP` |
| State "Hamburg" | country and region code | `country: DE`, `region: HH` |
| Rana "60%" | share of week, not a short week | `fte: 0.6`, no `workweek` |
| Joel "Left 2026-02-28" | stays in the file | membership `to: 2026-02-28` |
| "Fixed share 10%" for Ops console | fixed capacity share | `share: 0.1` |
| Sprint names `KW02-03` ... | map to ID scheme | `'2026.1'` ... in sheet order; `end` as given |
| Dates `05.01.2026` | ISO | `2026-01-05` |
| "Committed" / "Done" | commitment / finished | `forecast_ist` / `velocity` |
| "Added during sprint: 4" with commitment 22 | share, user confirmed points/commitment | `scope_creep: 0.18` (4/22 rounded to 2 decimals); blank rows stay `null` |
| Absence columns | working days, holidays not included | `absences` per person ID |
| Last sprint: no committed/done, partial absences | future sprint | `forecast_ist`, `velocity` null; `absence_state: expected` |
| Last sprint: Joel's absence blank | no data, not 0 | Joel omitted (not `0`) |
| `Absent Joel` = 0 in sprint 1 | explicit zero | `joel: 0` kept |

Check it:

```bash
bash skills/excel-import/scripts/check.sh skills/excel-import/examples/expected sheet-demo 2026-02-10
```

Expect no errors (notices about frozen capacity are normal for historic sprints).
