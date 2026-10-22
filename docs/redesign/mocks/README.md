# Foresprint 1.0 mockups

Clickable HTML mockups of the flows in [../flows.md](../flows.md), with the invented demo team "Team Atlas".

- Open `dist/foresprint-mocks.html` in a browser (no server needed). "Abläufe durchspielen" in the rail plays each flow step by step.
- Sources in `src/`: `base.css` (tokens from DESIGN.md), `data.js` (demo data), `app.js` (shell, router, helpers, flow guide), `views/*.js` (one file per area), `fonts/` (Iosevka and Iosevka Aile, OFL, subset to Latin).
- Build after a change: `python3 build.py` (inlines CSS, fonts and JS into `dist/foresprint-mocks.html`).
- Check: `impeccable detect --json dist/foresprint-mocks.html` (see ../impeccable.md).

Mock state lives in memory only; nothing is saved.
