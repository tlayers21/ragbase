# RAGbase Explain-Codebase Skill

## Purpose

`docs/CODEBASE_EXPLAINED.md` is a deep, developer-facing explanation of every file in the project. It is **gitignored** — private context for onboarding and AI assistance. Do not reference it in README or public docs.

---

## When to Generate or Update

- First-time setup (file doesn't exist yet).
- Significant new feature that adds or changes multiple files.
- New file added that isn't covered.
- Architecture change that makes existing explanations misleading.

Do NOT regenerate the whole file for small bug fixes. Update only the affected file entries.

---

## Document Structure

```
# RAGbase — Codebase Explained

## Project Overview
One paragraph: what RAGbase does, what runs where, why it exists.

## Key Design Decisions
Bullet list of the 5–8 most important architectural choices and why they were made.
(Examples: embedded ChromaDB, two-phase ingestion, no query rewriting, sequential graph builds)

## Module by Module
One section per directory, then one subsection per file.

## Tradeoffs and Known Limitations
Honest list of what was sacrificed for simplicity or speed.
```

---

## Per-File Format

```markdown
### filename.py

**What it does:** One sentence — the job of this file.

**Why it exists:** Why this is a separate file, not folded into another.

**Non-obvious behavior:** Anything that would surprise a developer reading this for the first time. If nothing, omit this field.

**Key functions:**
- `function_name(args)` — one-line explanation
- `function_name(args)` — one-line explanation

**Design decisions:** Why it was built this way. Reference alternatives that were considered or removed if relevant.
```

---

## Coverage Rules

- Every file listed in the Directory Structure section of `.ai/instructions.md` must have an entry.
- Subdirectory `__init__.py` files: skip unless they contain non-trivial logic.
- Generated files (`frontend/.next/`, `data/`, `*.pyc`): skip entirely.
- Scripts in `scripts/`: include, one entry per `.sh` file.

---

## After Generating

1. Read the Directory Structure section of `.ai/instructions.md`.
2. Verify every file listed there has an entry in `docs/CODEBASE_EXPLAINED.md`.
3. Verify no entry describes behavior that contradicts the Known Gotchas in `.ai/instructions.md`.
4. The file is gitignored — confirm it is listed in `.gitignore` before saving.
