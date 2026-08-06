# KaTeX v0.18.0 + rehype-katex v7.0.1 — RAGbase Reference

> Fetched via Context7 — 2026-08-06
> Versions: katex ^0.18.0, rehype-katex ^7.0.1, remark-math ^6.0.0

---

## rehype-katex Usage (unified/remark pipeline)

```javascript
import rehypeKatex from 'rehype-katex'
import rehypeStringify from 'rehype-stringify'
import remarkMath from 'remark-math'
import remarkParse from 'remark-parse'
import remarkRehype from 'remark-rehype'
import { unified } from 'unified'

const file = await unified()
  .use(remarkParse)
  .use(remarkMath)
  .use(remarkRehype)
  .use(rehypeKatex, {
    // Pass KaTeX options (all optional)
    fleqn: false,
    macros: { '\\RR': '\\mathbb{R}' },
    errorColor: '#cc0000',
    strict: 'warn',            // 'warn' | 'ignore' | 'error'
  })
  .use(rehypeStringify)
  .process(markdown)
```

Requires KaTeX CSS in the page:
```html
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.8/dist/katex.min.css">
```
(or import the npm package's CSS directly, as RAGbase does — see below).

---

## Math Syntax (remark-math)

`remark-math` parses `$...$` (inline) and `$$...$$` (block) into mdast nodes for `rehype-katex` to render. `singleDollarTextMath` (default `true`) controls whether single `$` triggers inline math.

```markdown
Inline math: $E = mc^2$

Display (block) math:
$$
\int_0^\infty e^{-x^2} dx = \frac{\sqrt{\pi}}{2}
$$

Multi-line:
$$
\begin{aligned}
  a &= b + c \\
  d &= e + f
\end{aligned}
$$
```

---

## Security: rehype-sanitize + math

For untrusted user markdown, combine `rehype-sanitize` with `rehype-katex`. Run sanitize **before** `rehypeKatex`, and extend the schema to keep the math-related classes remark-math emits:

```javascript
import rehypeKatex from 'rehype-katex'
import rehypeSanitize, { defaultSchema } from 'rehype-sanitize'
import rehypeStringify from 'rehype-stringify'
import remarkMath from 'remark-math'
import remarkParse from 'remark-parse'
import remarkRehype from 'remark-rehype'
import { unified } from 'unified'

const file = await unified()
  .use(remarkParse)
  .use(remarkMath)
  .use(remarkRehype)
  .use(rehypeSanitize, {
    ...defaultSchema,
    attributes: {
      ...defaultSchema.attributes,
      code: [
        ['className', /^language-./, 'math-inline', 'math-display'],
      ],
    },
  })
  .use(rehypeKatex)  // run AFTER sanitization
  .use(rehypeStringify)
  .process(userMarkdown)
```

---

## Direct KaTeX API (rarely needed — RAGbase goes through rehype-katex, not this directly)

```javascript
import katex from 'katex'

// Render to DOM element (browser only)
katex.render('c = \\pm\\sqrt{a^2 + b^2}', element, {
  throwOnError: false,
})

// Render to HTML string (server-side or innerHTML)
const html = katex.renderToString('c = \\pm\\sqrt{a^2 + b^2}', {
  throwOnError: false,
  output: 'html',
  displayMode: true,
})
```

### katex.render() / katex.renderToString() options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `throwOnError` | boolean | `true` | Throw `ParseError` on invalid LaTeX (set `false` for user content) |
| `output` | string | `"htmlAndMathml"` | `"html"` \| `"mathml"` \| `"htmlAndMathml"` — official default is `htmlAndMathml`, not `html` |
| `displayMode` | boolean | `false` | Block-style (centered, larger) rendering |
| `leqno` | boolean | `false` | Left-side equation numbers |
| `fleqn` | boolean | `false` | Flush left display math |
| `macros` | object | `{}` | Custom LaTeX command definitions |
| `errorColor` | string | `"#cc0000"` | Color for error text when `throwOnError=false` |
| `minRuleThickness` | number | — | Minimum rule/fraction bar thickness (em) |
| `colorIsTextColor` | boolean | `false` | Use legacy `\color` behavior (affects surrounding text, not just the argument) |
| `maxSize` | number | `Infinity` | Caps user-specified sizes (`\rule`, `\kern`, etc.) in ems |
| `maxExpand` | number | `1000` | Max macro expansion steps |
| `strict` | boolean \| string | `"warn"` | `false`, `"warn"`, or `"error"` — LaTeX compliance strictness |
| `trust` | boolean \| function | `false` | Allow `\url`, `\href`, etc. |
| `globalGroup` | boolean | `false` | Persist `\gdef`/`\let` definitions into the passed `macros` object across calls |

### Persistent macros

Share one `macros` object across multiple render calls so `\gdef` definitions persist between elements:

```js
const macros = {}
for (const element of mathElements) {
  katex.render(element.textContent, element, { throwOnError: false, macros })
}
```

---

## Error Types

```javascript
import katex from 'katex'

try {
  katex.render('\\invalid{', element, { throwOnError: true })
} catch (e) {
  if (e instanceof katex.ParseError) {
    console.error('LaTeX parse error:', e.message)
  }
}
```

With `throwOnError: false`: invalid LaTeX renders as red source code with the error as a hover tooltip. This is the safe default for user-generated content.

---

## Common Pitfalls

- **Blank boxes** — KaTeX CSS not imported. Import `katex/dist/katex.min.css` once at the app root.
- **Backslash escaping in JS strings** — `'\\frac{1}{2}'` renders as `\frac{1}{2}`. A single backslash `'\frac{1}{2}'` is a JS string escape and silently produces wrong output.
- **`throwOnError: true` default** — throws and breaks the component on any invalid LaTeX. Always use `throwOnError: false` for user-generated content.
- **Plugin order** — `remarkPlugins={[remarkMath]}` must come before `rehypePlugins={[rehypeKatex]}`. remark-math parses the `$...$` syntax; rehype-katex renders the parsed AST nodes. Reversing them silently produces no math rendering.
- **Block math on its own line** — `$$...$$` must have blank lines before/after in the markdown to render as a block. Inline `$$` in a paragraph renders as inline (smaller).
- **`output` default is `"htmlAndMathml"`**, not `"html"` — both markup languages get emitted unless you explicitly restrict it. Harmless for rendering but doubles the emitted markup if you're inspecting output size.

---

## Supported LaTeX Subset

KaTeX covers a large subset of LaTeX. Commonly used in RAGbase content:

```
\frac{a}{b}          fractions
x_i, x^2            subscripts, superscripts
\alpha, \beta, \sigma  Greek letters
\int, \sum, \prod    integrals, sums, products
\sqrt{x}             square root
\mathbf{x}, \vec{v}  bold, vector notation
\begin{matrix}...\end{matrix}  matrices
\begin{aligned}...\end{aligned}  aligned equations
```

Full support table: https://katex.org/docs/support_table

---

## RAGbase-Specific Notes

KaTeX is used through react-markdown plugins, not directly. The full setup:

```tsx
// app/globals.css or app/layout.tsx — import CSS once at app level
import 'katex/dist/katex.min.css'

// MessageBubble.tsx
import Markdown from 'react-markdown'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'

<Markdown
  remarkPlugins={[remarkMath]}
  rehypePlugins={[rehypeKatex]}
>
  {content}
</Markdown>
```

That's the complete RAGbase setup. No direct KaTeX API calls are made, and RAGbase uses all rehype-katex defaults — no custom `rehypeKatex` options configured.
