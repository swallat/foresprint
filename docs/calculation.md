# Calculation

How sprintforecast turns the [data files](data-format.md) into a forecast. Every figure can be
traced with the numbers substituted: in the web UI through tooltips (the "i" next to figures and
column headers) and the collapsible **Calculation** on the Forecast and Planning pages, on the
command line with `sprintforecast forecast TEAM --explain SPRINT` (`-` = the next planning).
`sprintforecast capacity TEAM [SPRINT]` shows the capacity calculation in detail.

## Figures

| Figure | Formula |
|---|---|
| Normalized velocity | velocity / capacity x reference capacity |
| Average | mean of the last `window` sprints **with a value**, only if the sprint itself has a value; sprints without a value (gaps) do not count, the window reaches further back |
| Trend | extrapolation of the average into the future (never negative) |
| Forecast PLAN | normalized velocity trend / reference x capacity, rounded down to 1 decimal, never negative; for past sprints: the commitment |
| Plannable / small items | Forecast PLAN x plannable share (default 0.8, key `roadmap_share`) / the rest |
| Fulfillment | velocity / commitment |
| Planning delta | Forecast PLAN - (carryover + backlog - corrections) |
| Done | finished tickets **plus** the parts of open tickets finished within the sprint (team practice); should be counted consistently in the team, otherwise velocity and done are not comparable across a change of practice |
| Default per product | available x `share` (fixed share, optional), or (available - sum of fixed shares) / number of products without `share`; available = Forecast PLAN (frozen at planning, otherwise current) or its plannable share |
| Balance per product | sum of done - sum of default over the sprints in which done is recorded for the product (missing is not 0: sprints without a value do not count); fixed shares must not add up to more than 100 % |

**New teams:** a first forecast appears from **3 sprints with velocity** ("thin history": average
of all available sprints, extrapolated flat, with the warning "Little data"); the full window
(`window`, default 5) and the threshold of 5 sprints for reliable statements come later.

## Capacity of a sprint

In this order:

1. `capacity` in the sprint file (frozen or manual): source *recorded*
2. With a people list, capacity is **always calculated from calendar and people** (public
   holidays, sprint length, working week, FTE); only the *unknown absences* are estimated.
   Depending on the sprint's **absence state** (`absence_state`):
   - *confirmed* (absences recorded or explicitly "nobody absent"): sum over people of
     (working days - public holidays - absences) x FTE - overhead: source *people list*
   - *announced* (PO pre-planning): the same with the announced absences: source *announced
     absences*
   - *unknown*: calendar and people, reduced by the average absences of the last
     `absence_history` sprints **with confirmed absences** (confirmed sprints without absences
     count as 0; the sprints used are shown on the *Prepare sprint: Absences* page): source
     *expected absences*; if there is no such history yet, without deduction: source *calendar,
     absences unknown* (warning)
3. Only **without a people list**: capacity trend: source *trend* (warning)

**Overhead for Scrum ceremonies** (one shared calculation for confirmed, announced and expected
absences): first public holidays and absences per person, then the overhead. The capacity stays
unrounded (the forecast keeps calculating with it); it is rounded half up only for display and
when frozen in the review, to `capacity.rounding` decimals (default 1), the same everywhere, so
one value is never shown in two different ways. The equations in the calculation show the
numbers actually used (capacity and trend with up to 4 decimals, for example
`16.8433 / 45 x 25.25`); the Forecast PLAN stays rounded down. Fixed PD per person
(`overhead_days` x FTE, at most the person's capacity) **replace** the percentage
(`overhead_share`); both are the same deduction in two units and are not added.

## Trend modes

`forecast.trend_mode`:

- `flat` (default): the last average stays constant (robust).
- `classic`: 1st future sprint linear `avg + (avg - avg_before)`, 2nd multiplicative
  `avg_second_last / avg_third_last x trend_before`, then linear.
- `linear`: linear throughout.

Example (last average 44, before that 40, three future sprints): `flat` gives 44, 44, 44;
`linear` gives 48, 52, 56; `classic` gives 48, 52.8 (44/40 = +10 % on 48), 57.6. The mode can be
changed at any time; no data is lost, the forecast is only recalculated.

Warning: `classic` and `linear` also extrapolate noise. The forecast can rise or fall and, with a
longer horizon, quickly leaves the range. Choose them only deliberately (the UI warns). The
forecast is never negative. If the history is too short for the chosen mode (for example exactly
`window` sprints), `flat` applies with the note "thin history".

## Uncertainty

The forecast tiles show the range (lowest to highest normalized velocity of the last sprints)
and warn when fewer than 5 sprints have a velocity. Statements such as "in 85 % of the
simulations" are model-dependent frequencies from the history (the sample is shown), not
promises.

**Current forecast / forecast at planning:** the "current forecast" is the Forecast PLAN
calculated today, the "forecast at planning" the state frozen at planning (basis of the
distribution per product); where both appear, they are shown separately with their difference.

## Supplementary analyses

`sprintforecast analysis TEAM [--remaining AMOUNT] [--total] [--share PERCENT]` or the
**Analysis** page, in addition to the forecast; the existing figures stay unchanged:

- **Range:** forecast with the lowest, middle and highest normalized velocity of the last sprints
  (conservative / middle / optimistic).
- **Focus factor:** velocity / capacity, the same quantity as the normalized velocity, only
  without the reference capacity (normalized velocity = focus factor x reference capacity). It
  depends on the estimation unit (with story points on the team's estimation scale) and is
  therefore **not** comparable between teams; it shows the trend within one team.
- **Buffer:** average scope creep of the last sprints compared with the small-items share.
- **When will it be done?** Monte Carlo simulation starting with the next sprint: in which sprint
  a remaining amount is finished in 50 % and in 85 % of the simulation runs (model-dependent
  frequency from the last `window` sprints, not a promise; the sample and a warning for little
  data are shown), with the plannable share or (`--total`) the whole forecast, optionally with
  only a **project share** of it (`--share 50` = half). Teams without a people list calculate
  with the average capacity.

The report `FORECAST.md` ends with a section "Supplementary: range".
