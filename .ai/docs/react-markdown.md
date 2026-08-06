# react-markdown v10.1.0 — RAGbase Reference

> Fetched via Context7 — 2026-08-06
> Version: ^10.1.0

---

## Core API

```tsx
import Markdown from 'react-markdown'

<Markdown>{markdownString}</Markdown>
```

Three exports depending on async plugin needs:
- `Markdown` — synchronous (used in RAGbase)
- `MarkdownAsync` — supports async plugins server-side
- `MarkdownHooks` — supports async plugins client-side

---

## All Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `children` | `string` | — | Markdown content |
| `remarkPlugins` | `PluggableList` | `[]` | Remark plugins (markdown AST transforms) |
| `rehypePlugins` | `PluggableList` | `[]` | Rehype plugins (HTML AST transforms) |
| `components` | `Components` | — | Custom React components for HTML elements |
| `remarkRehypeOptions` | `object` | — | Options passed to remark-rehype conversion |
| `allowedElements` | `string[]` | all | Whitelist of permitted HTML tags |
| `disallowedElements` | `string[]` | `[]` | Blacklist of forbidden HTML tags |
| `allowElement` | `(element, index, parent) => boolean` | — | Custom per-element filter |
| `skipHtml` | `boolean` | `false` | Ignore/remove raw HTML in markdown instead of escaping it |
| `unwrapDisallowed` | `boolean` | `false` | Keep the text content of disallowed elements instead of dropping it |
| `urlTransform` | `(url, key, node) => string \| null` | `defaultUrlTransform` | Sanitize/rewrite URLs; return `null`/`''` to drop the attribute |

Only one of `allowedElements` / `disallowedElements` may be used at a time.

---

## Custom Component Renderers

```tsx
<Markdown
  components={{
    // Simple tag remap
    h1: 'h2',

    // Custom component (receives node + all HTML props)
    em({ node, children, ...props }) {
      return <i style={{ color: 'red' }} {...props}>{children}</i>
    },

    // External links open in a new tab
    a({ node, href, children, ...props }) {
      return (
        <a href={href} target="_blank" rel="noopener noreferrer" {...props}>
          {children}
        </a>
      )
    },

    // Custom code block (inline vs fenced) — `inline` is inferred from className presence
    code({ node, className, children, ...props }) {
      const match = /language-(\w+)/.exec(className || '')
      return match ? (
        <pre className="bg-muted rounded-lg p-4 overflow-x-auto">
          <code className={className} {...props}>{children}</code>
        </pre>
      ) : (
        <code className="bg-muted px-1 rounded text-sm" {...props}>{children}</code>
      )
    },

    // Access node position info
    p({ node, children }) {
      return <p data-line={node.position?.start.line}>{children}</p>
    },
  }}
/>
```

**Supported element keys**: `a`, `blockquote`, `br`, `code`, `em`, `h1`–`h6`, `hr`, `img`, `li`, `ol`, `p`, `pre`, `strong`, `ul`.
With `remark-gfm`: also `del`, `input`, `table`, `tbody`, `td`, `th`, `thead`, `tr`.

Every custom component receives `node` — the original hast element. Destructure it out (`{ node, ...props }`) if you don't need it, so it isn't spread onto the DOM element.

---

## remarkPlugins / rehypePlugins

```tsx
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeRaw from 'rehype-raw'
import rehypeSanitize from 'rehype-sanitize'
import rehypeKatex from 'rehype-katex'

// GitHub Flavored Markdown: tables, strikethrough, task lists, autolinks
<Markdown remarkPlugins={[remarkGfm]}>{gfmMarkdown}</Markdown>

// Plugin with options — pass as a tuple
<Markdown remarkPlugins={[[remarkGfm, { singleTilde: false }]]}>{text}</Markdown>

// Math rendering
<Markdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>{content}</Markdown>

// Raw HTML passthrough (use with caution) + sanitize for untrusted content
<Markdown rehypePlugins={[rehypeRaw, rehypeSanitize]}>{content}</Markdown>

// Multiple plugins combine freely
<Markdown
  remarkPlugins={[remarkGfm, remarkMath]}
  rehypePlugins={[rehypeRaw, rehypeKatex]}
>
  {complexMarkdown}
</Markdown>
```

Plugin order matters within each array — `remarkPlugins` always run before `rehypePlugins` in the pipeline.

---

## Processing Pipeline

```
markdown string
  → remark parser → mdast (markdown AST)
  → remarkPlugins (e.g. remark-math: parses $...$ nodes)
  → remark-rehype → hast (HTML AST)
  → rehypePlugins (e.g. rehype-katex: renders math nodes as HTML)
  → React elements
```

---

## Security

`defaultUrlTransform` blocks dangerous protocols (e.g. `javascript:`) while allowing `http`, `https`, `irc`, `ircs`, `mailto`, `xmpp`, and relative URLs:

```tsx
import Markdown, { defaultUrlTransform } from 'react-markdown'

defaultUrlTransform('https://example.com')     // 'https://example.com'
defaultUrlTransform('javascript:alert(1)')     // ''
defaultUrlTransform('/relative/path')          // '/relative/path'
```

Override with a custom `urlTransform` to proxy/prefix URLs or drop attributes entirely (return `null`):

```tsx
<Markdown
  urlTransform={(url, key, node) => {
    if (key === 'src' && node.tagName === 'img') {
      return `https://proxy.example.com/?url=${encodeURIComponent(url)}`
    }
    return url
  }}
>
```

For untrusted content that also uses `rehypeRaw` (raw HTML passthrough), add `rehypeSanitize` **after** `rehypeRaw` (and before any plugin like `rehypeKatex` that depends on the classes surviving sanitization — adjust the schema to allow `language-math`/`math-inline`/`math-display` classes if combining with math).

`skipHtml` removes raw HTML entirely instead of escaping it — useful when you don't want `rehypeRaw` and just want raw HTML stripped rather than shown as literal text.

---

## Common Pitfalls

- **KaTeX CSS missing**: math renders as blank boxes without `katex/dist/katex.min.css` imported.
- **Plugin order**: `remark-math` must be in `remarkPlugins`; `rehype-katex` must be in `rehypePlugins`. Swapping them silently produces no math rendering.
- **Inline vs block math**: `$x^2$` = inline, `$$x^2$$` = block (own line in markdown).
- **`node` prop**: always destructure it out if unused — `{ node, ...props }` — to avoid passing it to the DOM element.
- **`inline` prop on `code`**: not passed directly by react-markdown v10 — infer inline vs. block by checking for a `language-*` className (fenced blocks get one, inline code doesn't).

---

## RAGbase-Specific Notes

Math rendering setup used in `MessageBubble`:

```tsx
import Markdown from 'react-markdown'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'   // import once at app root, not per component

function MessageBubble({ content }: { content: string }) {
  return (
    <Markdown
      remarkPlugins={[remarkMath]}
      rehypePlugins={[rehypeKatex]}
    >
      {content}
    </Markdown>
  )
}
```

**Plugin versions used in RAGbase:**
| Package | Version |
|---------|---------|
| `remark-math` | ^6.0.0 |
| `rehype-katex` | ^7.0.1 |
| `katex` | ^0.18.0 |
