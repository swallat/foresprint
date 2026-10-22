# Questions to ask the user

Ask these before writing files. Bundle related questions; propose a default and say why, so the
user can answer with one word. Never answer them yourself from guesses.

## About the team
1. Team name, sprint length in days, and which sprint is running now or starts next?
2. Do you estimate in story points or person days? (`unit: SP` or `PT`)
3. Country and, if holidays differ by region, the state/province. Does anyone work in another
   country or have their own working week?
4. Which optional parts do you want? Products with product owners (`features.products`, `po`),
   production access (`production`), ticket pre-planning (`tickets`)? Default: only what the
   workbook has data for.

## About people
5. Which sheet lists who is in the team, and from/to when? Who has left? (They stay in the file
   with an end date.)
6. Part-time: is it a share of a normal week (`fte: 0.6`) or a shorter week (`workweek`)? Never both.

## About sprint history
7. Which column is the commitment at planning ("committed") and which is done at the end?
   Does "done" include parts of unfinished tickets? (Only note it; Foresprint counts the same way
   consistently, and the team should too.)
8. Is there a "added during the sprint" figure, and as a share of the commitment or as points?
   (`scope_creep` is a share: 0.2 = 20 %.) If unclear, leave it `null`.
9. Absences: days or hours, per person and sprint, or date ranges? Are public holidays already
   deducted? (Do not enter them; the calendar knows them.) What is a half day?
10. Was the capacity frozen in a past sprint, or is it only calculated? Default: leave `capacity: null`.

## About products and tickets
11. How are products and their owners named; is a fixed capacity share agreed for any?
12. Per-product done values per sprint: which columns? (Only if products are on.)
13. Ticket list present? Which columns are key, title, estimate, status, epic, labels, sprint?

## When something does not fit
Say what you found, offer two options, recommend one. Examples: two sprints overlap; a person is
absent but not a member; the unit changes halfway through the history; totals disagree with
the rows.
