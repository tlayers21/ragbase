# RAGbase Frontend Skill

## Stack

- **Next.js 16** (App Router), **React 19**, **TypeScript**, **Tailwind CSS v4**
- **react-pdf** — PDF preview in SourcesModal (full preview + grid thumbnails)
- **KaTeX** — math rendering in MessageBubble via ReactMarkdown + remark-math/rehype-katex
- **pdfjs-dist** — lazy-imported in `lib/attachments.ts` for attachment page count only
- **next-themes** — light/dark/system theme

Dev server: `cd frontend && npm run dev` (port 3000)
Type check: `cd frontend && npx tsc --noEmit`
Production build: `npm run build` (never use dev server to verify prod behavior)

Read `frontend/AGENTS.md` before writing Next.js code — this project pins a Next.js version
with breaking API changes from what most training data assumes; check
`node_modules/next/dist/docs/` before relying on remembered Next.js conventions.

---

## Directory Layout

```
frontend/
├── app/
│   ├── page.tsx          — main 3-panel layout (Sidebar | ChatArea | SourcesPanel),
│   │                        owns source-selection state and the SourcesModal
│   └── settings/         — display name, API URL, theme, telemetry toggle
├── components/
│   ├── layout/           — Sidebar (chat session list), SourcesPanel, ThemeToggle
│   ├── chat/              — ChatArea, MessageBubble, ChatInput, SourceFilter,
│   │                        ModelSelector
│   ├── sources/           — DropZone, SourcesModal, PDFPreview, PDFThumbnail
│   ├── ui/                — ConfirmDialog
│   └── providers.tsx      — next-themes ThemeProvider wrapper
├── hooks/                 — useChat, useSources, useIngestion, useSettings
├── types/index.ts          — ALL shared types (@/types): SourceSummary, IngestionJob,
│                             Message, ChatSession, CitedChunk, MessageAttachment,
│                             PendingAttachment, QueryMode, AttachmentType
└── lib/
    ├── api.ts             — ALL typed API calls; consumeQueryStream SSE handler
    ├── config.ts          — DEFAULT_API_URL only (no DEFAULT_USER_ID)
    ├── attachments.ts     — classifyFile(), getPdfPageCount(), twoLinePreview(),
    │                         PASTE_TEXT_THRESHOLD=5000
    └── utils.ts           — cn() (clsx + tailwind-merge), deriveSourceName()
```

---

## Conventions

### API calls
- **All** API calls go through `lib/api.ts`. Never use `fetch` directly in components or hooks.
- API base URL is read from localStorage or `DEFAULT_API_URL` in `lib/config.ts`. Never hardcode `localhost:8001`.
- No `user_id` in any request — backend reads it from `data/user_id.txt`.

### SSE streaming
- `consumeQueryStream()` in `lib/api.ts` is the single SSE consumer, shared by `streamQuery()`,
  `streamDirectQuery()`, `streamAttachmentQuery()`.
- SSE events: token data, `[STAGE]{...}`, `[SOURCES]{...}`, `[ATTACHMENTS]{...}`, `[HEARTBEAT]`, `[DONE]`.
- Components call the hook (`useChat`), never consume SSE directly.

### State management
- React hooks only (`useState`, `useReducer`, `useRef`, `useCallback`). No Redux, Zustand, or other libraries.
- Chat state is multi-session: `useChat` holds a `ChatSession[]` persisted to
  `localStorage` (`ragbase_sessions`), not a single conversation. Always read/write through
  `activeSession`, never assume there's exactly one thread.
- Shared state lives in hooks under `hooks/`. Components receive it as props or consume hooks directly.

### Styling
- Tailwind utility classes only. No inline `style={{}}` except where Tailwind cannot express it (e.g. explicit `height` for react-pdf container).
- Dark mode via CSS variables — never hardcode `#hex` or `rgb()` color values.
- Theme toggle stamps `data-theme`/theme class via `next-themes`; use `:root[data-theme="dark"]` in global CSS if needed.
- No Tailwind `dark:` prefix — CSS variables handle theming.

### TypeScript
- Strict mode. No `any` without a comment explaining why.
- Shared types live in `types/index.ts` (import via `@/types`) — API response shapes and
  app-local types (`Message`, `ChatSession`, attachments) are defined there, not scattered
  across hooks/components.

---

## Common Gotchas

- **Multi-session chat** — `useChat` manages a list of `ChatSession` objects (id, title,
  messages, createdAt/updatedAt, pinned), not a single thread. The Sidebar lists sessions
  (pinned + recent) with rename/pin/delete. `GET /sessions/should_reset` is polled once on
  mount; a `true` response (set by `scripts/reset_all.sh`) clears `ragbase_sessions` from
  `localStorage`.
- **react-pdf `options` prop** — must be wrapped in `useMemo`. A new object reference on every render causes an infinite re-render loop.
- **react-pdf layers** — always pass `renderTextLayer={false}` and `renderAnnotationLayer={false}`.
- **react-pdf container height** — use explicit `style={{ height: "65vh" }}`, not `h-full`; Tailwind `h-full` doesn't give the scroll container a defined height.
- **react-pdf CDN worker** — URL must match the exact installed `pdfjs-dist` version:
  `https://cdn.jsdelivr.net/npm/pdfjs-dist@{version}/build/pdf.worker.min.mjs`
  Check version: `grep '"version"' frontend/node_modules/pdfjs-dist/package.json`.
  `PDFThumbnail.tsx` instead points at a same-origin `/pdf.worker.min.mjs` — keep both in sync
  if the pdfjs-dist version changes.
- **Focus rings** — the input's outer container (`focus-within:border-border/80`) carries the
  visible focus treatment; inner `<textarea>`/buttons use `outline-none`. Don't add
  `focus:ring-*` to inner elements.
- **Attachment paste** — image paste via `clipboardData.items`; text over `PASTE_TEXT_THRESHOLD` (5000 chars) becomes an attachment card (call `e.preventDefault()`).
- **Abort-then-send race** — `useChat.sendMessage()` aborts any in-flight stream and waits 100ms before starting a new one. Don't bypass this.
- **Context window bar** — estimates tokens as `chars/4 + 1500` per exchange. Auto-compact fires at 90% of 40,960 token limit, only once the session has more than 10 messages.
- **KaTeX** — rendered via `ReactMarkdown` with `remark-math`/`rehype-katex`. Don't add a separate KaTeX `<script>` tag.
- **Sources modal thumbnails** — `SourceThumbnail` lazy-loads via `IntersectionObserver`, then
  issues a HEAD request to sniff content-type before choosing a PDF/image/text preview path.

---

## After Any Edit

```bash
cd frontend && npx tsc --noEmit
```

Fix all type errors before considering the change done.
