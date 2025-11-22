# neurotrends — agent briefing

## What this project is
- Static site that visualizes “neurons simultaneously recorded vs. year.”
- Data lives in `neural_recording_papers.csv`.
- `src/build_site.py` (FastHTML + pandas) generates `public/index.html` and embeds the JSON payload.
- Frontend uses Observable Plot UMD for the chart and Tailwind (centralized) for styling.

## Build & preview
1) `uv venv && source .venv/bin/activate`
2) `uv pip install -r requirements.txt`
3) `npm install`
4) `npm run build:css`
5) `uv run python src/build_site.py`
6) Preview: `npx serve public` (or `cd public && python -m http.server 5173`)

## Deploy (Vercel)
- `npm run deploy` (wraps `vercel --prod --yes`). Requires prior `vercel login`.
- `vercel.json` points Vercel at the static `public/` output.

## Styling rules
- All design lives in `styles/input.css` using Tailwind `@apply`. Do **not** scatter utility classes in HTML/JS; extend or tweak in that single CSS entrypoint.
- Keep the current minimal paper-on-dark aesthetic (Fira Code, muted palette); avoid “glassy Linear” defaults.

## Plot contract
- Chart logic: `public/assets/plot.js` (Observable Plot).
- Payload keys from `build_site.py`: `points`, `methodRegressions`, `references`, `xRange`, `maxNeurons`.
- Tooltips are driven by Plot’s `input` event and must include clickable DOI links; keep pointer handling inside `plot.js`.

## Files you’ll usually touch
- Data: `neural_recording_papers.csv`
- Generator: `src/build_site.py`
- Styles: `styles/input.css`
- Plot behavior: `public/assets/plot.js`

## Guardrails
- Stick to ASCII unless the file already uses Unicode.
- Preserve static-host friendliness—no server/runtime additions.
- If adding new styling patterns, centralize them in `styles/input.css`.

## Git workflow (commit quality)
- Keep history in this repo; initialize with `git init` if absent.
- Commit early/often with descriptive, imperative summaries, e.g. `feat: add modality milestones to plot tooltips`.
- Include scope when helpful (`plot`, `build`, `docs`), keep body short but explicit about *why*.
- Suggested flow: `git add -A && git commit -m "scope: summary"`; avoid committing `node_modules/`, `.venv/`, `.vercel/` (see `.gitignore`).
- To publish: add the GitHub remote (`git remote add origin git@github.com:<your-username>/neurotrends.git`) then `git push -u origin main`.
