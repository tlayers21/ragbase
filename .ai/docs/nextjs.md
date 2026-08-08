# Next.js 16.2.10 — RAGbase Reference

> Fetched via Context7 — 2026-08-06
> Version: 16.2.10 (App Router)
> Re-fetch when version changes or docs feel stale

This Next.js version has breaking changes vs. typical training data — this file reflects the v16.2.9 official docs pulled live via Context7 (closest indexed version to the installed 16.2.10).

---

## File Conventions (App Router)

```
app/
├── layout.tsx        — root layout (shared UI, must have <html> + <body>)
├── page.tsx          — route page component, renders at "/"
├── loading.tsx       — Suspense fallback during page load
├── error.tsx         — error boundary component
├── not-found.tsx     — 404 page
├── globals.css       — global styles
└── settings/
    └── page.tsx      — renders at "/settings"
```

Pages are **Server Components** by default. Add `'use client'` for hooks and browser APIs.

---

## page.tsx — params & searchParams are Promises

Since Next.js 15, `params` and `searchParams` are **Promise-wrapped** and must be awaited (they were synchronous in 14 and earlier).

```tsx
// app/blog/[slug]/page.tsx
export default async function Page({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string }>
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>
}) {
  const { slug } = await params
  const { query } = await searchParams
  return <h1>Blog Post: {slug}</h1>
}
```

`generateMetadata` receives the same Promise-wrapped props and must await them too:

```tsx
export async function generateMetadata(props: {
  params: Promise<{ slug: string }>
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>
}) {
  const params = await props.params
  const searchParams = await props.searchParams
  return { title: `${params.slug} — RAGbase` }
}
```

Using `searchParams` opts the page into **dynamic rendering** (not statically generated).

### Reading params/searchParams in a Client Component

Client Components can't be `async`, so use React's `use()` to unwrap the promises instead of `await`:

```tsx
'use client'
import { use } from 'react'

export default function Page({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string }>
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>
}) {
  const { slug } = use(params)
  const { query } = use(searchParams)
}
```

### Dynamic params table:
| Route | URL | params |
|-------|-----|--------|
| `app/shop/[slug]/page.js` | `/shop/1` | `{ slug: '1' }` |
| `app/shop/[cat]/[item]/page.js` | `/shop/1/2` | `{ category: '1', item: '2' }` |
| `app/shop/[...slug]/page.js` | `/shop/1/2` | `{ slug: ['1', '2'] }` |

---

## layout.tsx

```tsx
// app/layout.tsx (root layout)
import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'RAGbase',
  description: 'Local AI knowledge base',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}
```

**Constraints:**
- Root layout **must** define `<html>` and `<body>` — do not add `<head>` tags manually; use the Metadata API.
- Layouts **do not re-render** on navigation (cached client-side). Cannot access `searchParams` or `pathname` directly — put those in Client Components using `useSearchParams()` / `usePathname()`.
- Layouts cannot pass data to `children` directly; use React `cache()` or Next.js fetch dedup.
- Non-root layouts also receive `params` as a `Promise` when the route has dynamic segments:

```tsx
export default async function DashboardLayout({
  children,
  params,
}: {
  children: React.ReactNode
  params: Promise<{ team: string }>
}) {
  const { team } = await params
  return (
    <section>
      <header><h1>Welcome to {team}'s Dashboard</h1></header>
      <main>{children}</main>
    </section>
  )
}
```

### Client-side interactivity from a Server Component layout

Keep the layout itself a Server Component and import a small Client Component for anything needing hooks (e.g. active-link highlighting):

```tsx
// app/layout.tsx (Server Component)
import { NavLinks } from '@/app/ui/nav-links'

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <NavLinks />
        <main>{children}</main>
      </body>
    </html>
  )
}
```

```tsx
// app/ui/nav-links.tsx
'use client'
import { usePathname } from 'next/navigation'
import Link from 'next/link'

export function NavLinks() {
  const pathname = usePathname()
  return (
    <nav>
      <Link className={pathname === '/' ? 'active' : ''} href="/">Home</Link>
    </nav>
  )
}
```

Context providers (theme, etc.) follow the same pattern — wrap `children` inside a Client Component boundary imported into the Server Component layout.

---

## Client Components

```tsx
'use client'    // must be at top of file

import { useState, useEffect, useCallback, useRef } from 'react'
import { useRouter, usePathname, useSearchParams } from 'next/navigation'

export default function Counter() {
  const [count, setCount] = useState(0)
  const router = useRouter()
  return <button onClick={() => { setCount(c => c + 1); router.push('/') }}>{count}</button>
}
```

**Must be Client Component** when: using `useState`, `useEffect`, `useRef`, `useCallback`, event handlers (`onClick`, `onChange`, etc.), browser APIs (`localStorage`, `window`), or any hooks.

---

## Navigation

```tsx
import Link from 'next/link'                    // declarative navigation
import { useRouter } from 'next/navigation'      // App Router — NOT 'next/router'

// Declarative
<Link href="/settings">Settings</Link>
<Link href={`/blog/${slug}`} prefetch={false}>Post</Link>

// Programmatic (client component)
const router = useRouter()
router.push('/settings')           // navigate + add to history
router.replace('/settings')        // navigate, replace history entry
router.refresh()                   // re-fetch server data for current route
router.back()                      // go back
router.prefetch(href)              // manual prefetch
```

`useRouter` must be imported from `next/navigation` in the App Router — importing from `next/router` (Pages Router API) throws.

---

## next.config.js

```js
// @ts-check
/** @type {import('next').NextConfig} */
const nextConfig = {
  /* config options here */
}
module.exports = nextConfig
```

```ts
// next.config.ts (redirects example)
import type { NextConfig } from 'next'

const nextConfig: NextConfig = {
  async redirects() {
    return [
      { source: '/about', destination: '/', permanent: true },
      { source: '/blog/:slug', destination: '/news/:slug', permanent: true },
    ]
  },
}
export default nextConfig
```

---

## Metadata API

```tsx
// Static metadata (layout or page)
import type { Metadata } from 'next'
export const metadata: Metadata = {
  title: 'RAGbase',
  description: 'Local AI knowledge base',
  icons: { icon: '/favicon.ico' },
}

// Dynamic metadata (page only)
export async function generateMetadata({ params }): Promise<Metadata> {
  const { slug } = await params
  return { title: `${slug} — RAGbase` }
}
```

---

## Build & Dev Commands

```bash
cd frontend && npm run build    # production — catches errors dev misses
cd frontend && npm run dev      # development (HMR, port 3000)
cd frontend && npx tsc --noEmit # type-check only
```

---

## RAGbase-Specific Notes

RAGbase is a single-page app (one route `/`). All components with state, effects, or event handlers use `'use client'`. Data fetching uses React hooks calling `lib/api.ts`, not server-side fetching.

```tsx
// All fetch calls via lib/api.ts — never fetch() directly in components
'use client'
import { useSources } from '@/hooks/useSources'

export function SourceList() {
  const { sources, isLoading } = useSources()
  return <ul>{sources.map(s => <li key={s.id}>{s.name}</li>)}</ul>
}
```

**API URL**: never hardcoded. Read from `localStorage` or `DEFAULT_API_URL` in `lib/config.ts`.

**Dark mode**: CSS variables (`data-theme` attribute on `<html>`), not Tailwind `dark:` prefix.

**Version gate**: this Next.js version has breaking changes from typical training data. `frontend/node_modules/next/dist/docs/` is the locally-vendored authoritative source — check that directory too when in doubt, not just this cache. (A `frontend/AGENTS.md` used to carry this warning; it has since been deleted.)
