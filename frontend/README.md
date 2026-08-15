# RAGbase frontend

The Next.js chat UI for [RAGbase](../README.md) — see the root README for what RAGbase
is and how to set up the whole app (Ollama, Python backend, models). This directory is
only the frontend half; on its own it has nothing to talk to.

## Stack

Next.js 16 (App Router) · React 19 · TypeScript · Tailwind v4

## Developing

```bash
npm install
npm run dev
```

Opens on `localhost:3000` and expects the FastAPI backend running at `localhost:8001`
(`python3 -m uvicorn main:app --port 8001` from the repo root — see the root README).

```bash
npx tsc --noEmit   # type-check
npm run build      # production build — required to verify PDF rendering, dynamic
                    # imports, and theming; the dev server bundles these differently
```

## Notes

- There is no separate deploy step. `scripts/install.sh` and `scripts/start.sh` in the
  repo root build and serve this app as part of RAGbase — it isn't deployed to Vercel or
  any other host; RAGbase runs entirely on your own machine.
- `frontend/public/static/sources` is a symlink to `../../../data/sources`, committed as
  a symlink (mode `120000`) so a fresh clone recreates it. Source file previews depend on
  it.
