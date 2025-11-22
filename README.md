# neurotrends

Static, no-build-runtime site that visualizes how many neurons are simultaneously recorded in published experiments. Data lives in `neural_recording_papers.csv`, the UI is assembled with [FastHTML](https://github.com/AnswerDotAI/fasthtml), styling goes through Tailwind, and Observable Plot draws the Epoch-style chart.

## Project layout

- `src/build_site.py` – reads the CSV, computes exponential trend fits (frontier max vs. all datapoints), and emits `public/index.html` with embedded JSON payloads for the chart.
- `styles/input.css` – lone Tailwind entrypoint that defines all classes via `@apply`, so tweaking the palette or spacing only happens in one place.
- `public/assets/plot.js` – hydrates the Observable Plot with tooltips, regression lines, and a legend.
- `vercel.json` – tells Vercel to serve `public/` as a static project (no server needed).

## Prereqs

- [uv](https://github.com/astral-sh/uv) (manages Python + virtualenv)
- Node.js 18+ (for Tailwind’s CLI)

## One-time setup

```bash
cd neurotrends
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
npm install
```

## Regenerating the site

```
# Rebuild the centralized CSS + FastHTML output
npm run build:css
uv run python src/build_site.py
```

Open `public/index.html` in a browser (or use `npx serve public`) to preview. Updating the CSV and rerunning those the two commands is enough to refresh the visualization.

During design work, `npm run dev:css` keeps Tailwind compiling while you tweak `styles/input.css`.

## Deploying to Vercel

1. Run the build commands above so `public/` has up-to-date assets.
2. `npm run deploy` (wraps `vercel --prebuilt --prod`), which publishes the contents of `public/` to the configured project (`neurotrends.vercel.app` once you’re logged in via `vercel login`).

## Customizing copy or styles

- All layout / typography tokens live in `styles/input.css`. Because the HTML only references semantic classes (`.nt-shell`, `.nt-plot`, …), you can drastically change the vibe without touching the Python or JS.
- Expanding the tooltip content only requires new columns in `neural_recording_papers.csv`. Any new fields will automatically flow into the hover card as long as you reference them in `public/assets/plot.js`.
- Observable Plot colors are defined in `public/assets/plot.js` via the `palette` array.

## Data provenance & citations

Each dot’s tooltip includes authors, publication venue, DOI, and the dataset source tag (Stevenson, Urai, etc.). The sidebar also summarises counts per source to simplify acknowledgements when citing the figure.
