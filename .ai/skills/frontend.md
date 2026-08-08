# RAGbase Frontend Skill

Everything needed to work on any component here without asking a clarifying question.
Read `.ai/instructions.md` first for the project-wide picture.

## Stack

Next.js **16.2.10** (App Router) · React **19.2.4** · TypeScript strict · Tailwind **v4**
· react-pdf 10 · react-markdown 10 + remark-math/rehype-katex · next-themes · lucide-react

```bash
cd frontend && npm run dev        # port 3000
npx tsc --noEmit                  # after EVERY edit — non-negotiable
npm run build                     # never verify production behavior on the dev server
```

**Next.js 16 is newer than most training data.** Before relying on remembered App Router
conventions, check the version-accurate docs in `frontend/node_modules/next/dist/docs/`
or the cached `.ai/docs/nextjs.md`. (`frontend/AGENTS.md` and `frontend/CLAUDE.md` used
to carry this note; both were deleted — don't cite them.)

---

## Directory layout

```
frontend/
├── app/page.tsx          3-panel layout; owns selectedSources + sources modal state
├── app/settings/         display name, API URL, theme, telemetry
├── components/
│   ├── layout/           Sidebar (session list, context bar), SourcesPanel, ThemeToggle
│   ├── chat/             ChatArea, MessageBubble, ChatInput, SourceFilter, ModelSelector
│   ├── sources/          DropZone, SourcesModal, PDFPreview, PDFThumbnail
│   ├── ui/               ConfirmDialog
│   └── providers.tsx     next-themes wrapper
├── hooks/                useChat, useSources, useIngestion, useSettings
├── lib/                  api.ts, config.ts, attachments.ts, utils.ts
└── types/index.ts        ALL shared types (@/types)
```

---

## Non-obvious patterns you must understand

### The SSE parser — `lib/api.ts::consumeQueryStream`

One parser, shared by `streamQuery()`, `streamDirectQuery()` and
`streamAttachmentQuery()`. The exact shape matters:

```ts
buffer += decoder.decode(value, { stream: true });
const frames = buffer.split("\n\n");
buffer = frames.pop() ?? "";          // last element is a partial frame — keep it

for (const frame of frames) {
  const line = frame.replace(/^\n+/, "").replace(/\r$/, "");   // framing only
  if (!line.startsWith("data:")) continue;
  const payload = line.startsWith("data: ") ? line.slice(6) : line.slice(5);

  if (payload === "[HEARTBEAT]") continue;
  if (payload === "[DONE]") { handlers.onDone(); return; }
  if (payload.startsWith("[SOURCES]"))     { /* JSON.parse the remainder */ continue; }
  if (payload.startsWith("[ATTACHMENTS]")) { /* ... */ continue; }
  if (payload.startsWith("[STAGE]"))       { /* ... */ continue; }

  handlers.onToken(JSON.parse(payload));   // tokens are JSON-encoded strings
}
```

Three things here are load-bearing:

1. **Never `.trim()` the frame.** Token payloads are frequently a single space or carry
   a meaningful trailing space. Trimming drops them and produces `"by8 equals96"`.
   Strip *only* leading newlines and a trailing `\r`.
2. **Tokens are JSON-encoded** (`api/query.py::_sse_token`). A raw `\n` inside
   `data: {token}\n\n` collides with the blank-line delimiter, so unencoded newline
   tokens vanish and every markdown list/heading/paragraph collapses onto one line.
   Control frames keep bare `[MARKER]` prefixes, so a payload starting with `"` is
   always a token.
3. **`reader.cancel()` resolves the pending `read()` with `done: true` rather than
   rejecting**, so an abort must be detected via `signal.aborted` and re-thrown as an
   `AbortError` — otherwise the caller's abort handling never runs.

Components never touch SSE directly; they call `useChat`.

### `useChat` state model

There is **no single conversation**. State is `ChatSession[]` persisted to
`localStorage` under `ragbase_sessions`; always operate on `activeSession`.

Per `sendMessage()` call, in order:
1. **Abort-then-send guard** — if a stream is open, abort it, `await` 100ms, reset
   `isLoadingRef`. Without the grace period the previous fetch's reader throws
   mid-teardown. **Do not remove this.**
2. `generationRef` is incremented; the `finally` block only clears loading state if
   `generationRef.current === gen`, so a superseded stream can't clear the new one's.
3. Create session if none active.
4. **Auto-compact** if `messages.length > 10` *and* estimated tokens ≥ 90% of 40,960:
   summarize all but the last 10 via `POST /compact`, replace them with one
   `role: "system", type: "summary"` message. Failure is non-blocking.
5. Push the user message plus an **empty assistant message**; tokens stream into it by id.
6. If it's the first message, fire-and-forget `POST /title` to replace the truncated title.
7. Stream via the endpoint matching the mode (attachments / direct / RAG).

**Attachment round-trip:** `description` (VLM output or extracted text) is stored on the
user `Message` and **never re-uploaded**. `historyContent()` folds it back into that
message's content when building `history` for later turns. The `[ATTACHMENTS]` event
patches descriptions onto the **user** message, positionally — it relies on the backend
processing attachments in the order they were sent.

**Mode selection lives in `app/page.tsx`, not the hook:**
```ts
const isDirectMode = selectedSources.size === 0;
const filter = !isDirectMode && sources.length > 0 && selectedSources.size < sources.length
  ? Array.from(selectedSources) : null;   // null = "all sources", never an empty array
```
Deselecting everything switches to `/query/direct`; a *strict subset* sends
`source_filter`. Never send an empty filter array.

### Why focus rings are removed from inner elements

The chat input is visually one control made of a textarea plus buttons. If each child
kept its own focus ring you'd see nested rings on tab-through. So the **outer container
carries `focus-within:border-border/80`** and every inner element uses `outline-none`.
Don't add `focus:ring-*` to inner elements — style the wrapper instead.

### Production build requirement

The dev server (Turbopack) differs from the production build in bundling, dynamic
imports and CSS ordering. `lib/attachments.ts` dynamically imports `pdfjs-dist` and
`SourcesModal` dynamically imports react-pdf with `ssr: false` — exactly the kind of
thing that works in dev and breaks in a build. **Verify anything touching dynamic
imports, PDF rendering, or theming with `npm run build`.**

### Ingestion polling

`useIngestion` uses a recursive `setTimeout` (not `setInterval`) so the delay adapts:
1s while any job is `queued`, 2s while `ingesting`, 3s otherwise. Polling stops
entirely when nothing is active and calls `onComplete?.()`.

Done jobs fade at 30s (`fadingJobIds`) then hide at 31s (`hiddenJobIds`). **Cancelled
jobs go into `hiddenJobIds` immediately** — filtering the local `jobs` array instead
would be undone by the very next poll.

---

## Conventions

- **All API calls go through `lib/api.ts`.** Never `fetch()` in a component or hook.
  (`SourcesModal` violated this and caused a real CORS-cache bug — see below.)
- **Never hardcode `localhost:8001`** — `DEFAULT_API_URL` in `lib/config.ts`, overridden
  from localStorage by `lib/api.ts` at call time.
- **Never send `user_id`** — the backend reads it from `data/user_id.txt`.
- **Shared types in `types/index.ts`**, imported as `@/types`.
- **React hooks only** — no Redux/Zustand. Shared state lives in `hooks/`.
- **Tailwind utilities only.** Inline `style={{}}` only where Tailwind can't express it
  (react-pdf's explicit container height).
- **Tailwind v4 is CSS-first** — no `tailwind.config.js`; tokens via `@theme inline {}`
  in `globals.css`. Dark mode uses `@variant dark (&:where(.dark, .dark *))`.
  **Never use the `dark:` prefix** and never hardcode hex/rgb — CSS variables carry theming.
- **No `any` without a comment** explaining why.

---

## Common mistakes

**Calling `fetch` directly in a component**
```tsx
const res = await fetch(`${url}/documents/`);        // ✗
const sources = await fetchSources();                 // ✓ from lib/api.ts
```

**Reusing one URL as both `<img src>` and `fetch()`** — the plain `<img>` request sends
no `Origin`, so the response has no `Access-Control-Allow-Origin`; the browser caches it
and reuses that entry for the CORS `fetch`, which then fails with a *misleading*
"blocked by CORS policy" on a file that serves fine.
```tsx
<img src={fileUrl} />                                 // ✗ if fetch() also hits fileUrl
<img src={fileUrl} crossOrigin="anonymous" />         // ✓ (backend also sends Vary: Origin)
```

**Fetching in an effect with no `AbortController`** — a component that unmounts mid-flight
(the source grid unmounts the instant a preview opens) leaves a request to fail late and
paint an error over a working view.
```tsx
useEffect(() => {
  const controller = new AbortController();
  fetchSourceType(source, controller.signal)
    .catch((e: Error) => { if (e.name !== "AbortError") setError(e.message); });
  return () => controller.abort();
}, [source]);
```

**Unmemoized react-pdf `options`** — a fresh object each render is an infinite reload loop.
```tsx
<Document options={{ cMapUrl: "/cmaps/" }} />                       // ✗
const options = useMemo(() => ({ cMapUrl: "/cmaps/" }), []);        // ✓
```
Also always pass `renderTextLayer={false}` and `renderAnnotationLayer={false}`, and give
the scroll container an explicit `style={{ height: "65vh" }}` — Tailwind `h-full` won't
give it a defined height.

**Mismatched pdfjs worker version** — must match the installed `pdfjs-dist` exactly
(currently **5.4.296**). `PDFPreview` uses the jsDelivr CDN URL; `PDFThumbnail` uses a
same-origin `/pdf.worker.min.mjs`; `lib/attachments.ts` has its own `PDFJS_VERSION`.
**All three must be updated together.**
```bash
grep '"version"' frontend/node_modules/pdfjs-dist/package.json
```

**Sending an empty `source_filter`** — means "no sources" to the backend. Use `null` for
"all", and switch to direct mode when nothing is selected.

**Assuming one conversation** — always read/write through `activeSession`.

**Adding a focus ring to an inner input/button** — style the wrapper's `focus-within:`.

**Using the `dark:` prefix** — theming is CSS variables, not Tailwind variants.

**Trusting the dev server for PDF/dynamic-import/theming changes** — run `npm run build`.

---

## Testing your change

Type-check is the floor, not the ceiling. To actually exercise ingestion, prompting,
citations or the sources modal in a real browser, use `.ai/skills/frontend-testing.md`
(headless Playwright — never the Chrome extension).
