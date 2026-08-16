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
- Source-file previews are served by `app/static/sources/[...path]/route.ts`, which streams
  originals out of `../data/sources` with byte-range support (pdf.js needs it). This used to
  be a `public/static/sources` symlink; Next only enumerates `public/` once at startup in a
  production build, so anything ingested after launch 404'd.
- pdf.js assets are local, never a CDN: `public/pdf.worker.min.mjs` is copied from
  `node_modules/pdfjs-dist` and must be refreshed when that package is upgraded.
  `lib/pdf.ts` is the only place the worker is configured. The cMaps that used to sit
  beside it were dropped — they are consulted only for non-Latin embedded font encodings,
  which this corpus does not have. Re-copy `node_modules/pdfjs-dist/cmaps/` and restore
  `cMapUrl`/`cMapPacked` in `PDFPreview.tsx` if that ever changes.
