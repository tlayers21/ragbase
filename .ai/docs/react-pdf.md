# react-pdf v10.4.x — RAGbase Reference

> Fetched via Context7 — 2026-08-06
> Version: ^10.4.1 (react-pdf by wojtekmaj — NOT @react-pdf/renderer)
> Re-fetch when version changes or docs feel stale

## Worker Setup (required)

Set the worker in the same module where you use react-pdf components — official docs: *"must be set in the same module where React-PDF components are used."*

```ts
import { pdfjs } from 'react-pdf'

// Recommended — local module resolution:
pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString()

// CDN alternative (RAGbase uses this pattern — URL must match installed pdfjs-dist version):
pdfjs.GlobalWorkerOptions.workerSrc = `//unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`
```

Bundler-specific notes:
- **Parcel 2**: prefix the specifier with `npm:` — `new URL('npm:pdfjs-dist/build/pdf.worker.min.mjs', import.meta.url)`.
- **CRA / no-eject setups** hitting `SyntaxError: expected expression, got <` or `ReferenceError: window is not defined`: use a CDN workaround, e.g. `//cdnjs.cloudflare.com/ajax/libs/pdf.js/${pdfjs.version}/pdf.worker.js`.
- A manual copy-to-output-dir approach is also documented for setups that serve the worker same-origin:
  ```ts
  import path from 'node:path'
  import fs from 'node:fs'
  const pdfjsDistPath = path.dirname(require.resolve('pdfjs-dist/package.json'))
  const pdfWorkerPath = path.join(pdfjsDistPath, 'build', 'pdf.worker.mjs')
  fs.cpSync(pdfWorkerPath, './dist/pdf.worker.mjs', { recursive: true })
  ```

Check installed version:
```bash
grep '"version"' frontend/node_modules/pdfjs-dist/package.json
```

---

## CSS Imports

```tsx
import 'react-pdf/dist/Page/AnnotationLayer.css'  // for links, annotations
import 'react-pdf/dist/Page/TextLayer.css'         // for text selection
```

Only needed if `renderTextLayer`/`renderAnnotationLayer` are enabled.

---

## Document Component

```tsx
import { Document } from 'react-pdf'

<Document
  file="https://example.com/sample.pdf"   // string URL, File, ArrayBuffer, or {url, httpHeaders, withCredentials}
  onLoadSuccess={(pdf: PDFDocumentProxy) => setNumPages(pdf.numPages)}
  onLoadError={(error: Error) => console.error(error)}
  onLoadProgress={({ loaded, total }) => console.log(loaded / total)}
  onSourceSuccess={() => {}}
  onSourceError={(error: Error) => {}}
  onItemClick={({ dest, pageIndex, pageNumber }) => {}}   // outline/thumbnail clicks
  onPassword={(callback: (password: string | null) => void, reason) => {}}
  options={pdfOptions}                     // MUST be memoized — see below
  loading="Loading PDF…"
  error="Failed to load PDF file."
  noData="No PDF file specified."
  renderMode="canvas"                      // "canvas" | "custom" | "none"
  rotate={0}                               // 0 | 90 | 180 | 270
  externalLinkTarget="_blank"
>
  {/* Page components go here */}
</Document>
```

Key callback type signatures:
```ts
type OnDocumentLoadSuccess = (document: PDFDocumentProxy) => void
type OnError = (error: Error) => void            // used for onLoadError and onSourceError
type OnPasswordCallback = (password: string | null) => void
type OnPassword = (callback: OnPasswordCallback, reason: PasswordResponse) => void
```
Note `onPassword`'s callback takes a `string | null`, not an `Error`.

`options` — additional PDF.js `DocumentInitParameters` (`cMapUrl`, `cMapPacked`, `httpHeaders`, `withCredentials`, etc.).

---

## Page Component

```tsx
import { Page } from 'react-pdf'

<Page
  pageNumber={1}                    // 1-indexed; alternative: pageIndex (0-indexed)
  renderTextLayer={false}
  renderAnnotationLayer={false}
  renderForms={false}               // default false
  renderMode="canvas"               // "canvas" | "custom" | "none"
  width={500}                       // pixels; or use scale
  scale={1}                         // zoom factor; overridden by width/height if set
  rotate={0}                        // per-page rotation override
  canvasBackground="white"          // any valid canvas.fillStyle
  canvasRef={ref}
  devicePixelRatio={window.devicePixelRatio}
  onRenderSuccess={(page: PageCallback) => {}}
  onRenderError={(error: Error) => {}}
  onLoadSuccess={(page) => {}}
  loading="Loading page…"
  error="Failed to load the page."
/>
```

`PageCallback` = `PDFPageProxy` augmented with `width`, `height`, `originalWidth`, `originalHeight`.

Canvas rendering internals (why `devicePixelRatio` matters): the canvas pixel buffer is sized via `page.getViewport({ scale: scale * devicePixelRatio })`, while the CSS display size uses `page.getViewport({ scale })` — this is what keeps rendering crisp on high-DPI screens without inflating the on-page CSS dimensions.

---

## Critical: Memoize the `options` Prop

```tsx
import { useMemo } from 'react'

// WRONG — new object every render → infinite reload loop
<Document options={{ cMapUrl: '/cmaps/' }} />

// CORRECT — stable reference via useMemo
const pdfOptions = useMemo(() => ({
  cMapUrl: '/cmaps/',
  cMapPacked: true,
}), [])

<Document file={url} options={pdfOptions} />

// ALSO CORRECT — module-level constant
const PDF_OPTIONS = { cMapUrl: '/cmaps/' }
<Document file={url} options={PDF_OPTIONS} />
```

Official docs: *"Make sure to define `options` object outside of your React component or use `useMemo` if you can't."*

---

## RAGbase-Specific Notes

- RAGbase uses the CDN worker pattern (URL must exactly match the installed `pdfjs-dist` version — check via `grep '"version"' frontend/node_modules/pdfjs-dist/package.json`), except `PDFThumbnail.tsx`, which instead points at a same-origin `/pdf.worker.min.mjs`.
- RAGbase always sets `renderTextLayer={false}` and `renderAnnotationLayer={false}` — avoids needing the layer CSS imports and avoids a react-pdf internal re-render loop.
- The `options` prop is always memoized (`useMemo` or a stable module-level constant) to avoid the infinite-reload bug described above.
- The scroll container needs an **explicit height** (e.g. `style={{ height: '65vh' }}`) — Tailwind's `h-full` doesn't give the scroll container a defined height when the parent lacks a fixed height, breaking scroll.

**Scrollable multi-page pattern (RAGbase):**

```tsx
function PDFPreview({ url }: { url: string }) {
  const [numPages, setNumPages] = useState(0)
  const pdfOptions = useMemo(() => ({}), [])  // stable reference

  return (
    <div style={{ height: '65vh', overflowY: 'auto' }}>   {/* explicit height required */}
      <Document
        file={url}
        onLoadSuccess={({ numPages }) => setNumPages(numPages)}
        options={pdfOptions}
      >
        {Array.from({ length: numPages }, (_, i) => (
          <Page
            key={`page_${i + 1}`}
            pageNumber={i + 1}
            renderTextLayer={false}         // avoids CSS issues
            renderAnnotationLayer={false}   // avoids re-render loop
            width={Math.min(600, window.innerWidth - 80)}
          />
        ))}
      </Document>
    </div>
  )
}
```
