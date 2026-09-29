# Investigator workspace (React + TypeScript + Vite)

The dense, read-only investigator console for the crypto-attribution project.
It is served by the FastAPI app at **`/investigator`** in non-prod builds and
reads only allow-listed saved artifacts through the read-only facade at
`/api/v1/demo` plus `/api/v1/meta`. It never traces live, opens a provider, or
holds case PII.

The older server-rendered console (`/console`, `/graph`, `/dashboard`,
`/neighborhood/vasp/...`) still exists as a fallback and for printable reports.

## Run

```bash
# from the repo root, serve API + built workspace in one process:
make demo            # http://127.0.0.1:8010/investigator

# dev server with API proxy (API expected on :8000 via `make dev`):
make frontend-dev    # http://127.0.0.1:5173/investigator/
```

`vite.config.ts` proxies `/api`, `/healthz`, and `/readyz` to
`VITE_API_PROXY` (default `http://127.0.0.1:8000`).

## Checks

```bash
npm run lint         # oxlint
npx tsc -b           # typecheck
npm run test         # vitest + testing-library
npm run build        # tsc -b && vite build  ->  dist/
```

## Layout

```
src/
  lib/        api client, formatting, status vocabulary, auth, shared styles
  components/ shell, nav, tables, inspector, primitives, login
  graph/      Cytoscape fund-flow graph (lazy-loaded chunk)
  pages/      one file per workspace route
  test/       vitest setup and tests
```

Design tokens live in `src/index.css`. Status colours are always paired with
an icon and a text label; no state is communicated by colour alone.
