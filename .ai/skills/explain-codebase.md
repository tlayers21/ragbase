# RAGbase Explain-Codebase Skill

## Purpose

`docs/CODEBASE_EXPLAINED.md` is the long-form "senior engineer explaining the system to
a smart new hire" document. It answers *why*, where `.ai/instructions.md` answers *what*
and *how*.

**It is committed to git** (`git ls-files docs/` confirms it — despite older notes
claiming otherwise). Treat edits as real repo changes, and never rewrite it wholesale
without being asked: it's owner-curated, and a full regeneration discards their edits.
It is listed under "never edit autonomously" in `master.md` for exactly this reason.

## When to update

- A new feature spans multiple files and the narrative no longer matches.
- A new file exists with no entry.
- An architecture change makes an existing explanation actively misleading.

**Update only the affected entries** for a bug fix or a small change. Full regeneration
is an explicit request, not a default.

## Document structure

```
# RAGbase — Codebase Explained

## What RAGbase is            The problem, who it's for, why local-first
## How a query works          End to end, one request, every layer it touches
## How ingestion works        End to end, both phases
## Module by module           One section per directory, one subsection per file
## Architecture decisions     Each major choice, argued — including what it costs
## Known tradeoffs            What was deliberately left simple, and the bill for it
## Data flow                  Raw document → chunks → graph → cached response
```

The two end-to-end walkthroughs are the most valuable part. They're what lets someone
hold the system in their head; the per-file reference is what they return to later.

## Per-file format

```markdown
### filename.py

**What it does:** One sentence.

**Why it exists:** What would break, or what would get worse, without it.

**Non-obvious behavior:** What would surprise a careful reader. Omit if genuinely none.

**Key functions:**
- `name(args)` — what it actually does, not a restatement of the name

**Design decisions:** Why this way. Name the alternative that was rejected and why.
```

## Rules that keep it honest

1. **Read the code, not the docs.** Every claim must be verified against the source. If
   `.ai/instructions.md` and the code disagree, the code wins — and fix instructions.md too.
2. **Explain the *why*, and name the cost.** "Embedded ChromaDB" is a fact; "embedded so
   there's no Docker dependency, at the cost of being single-process" is an explanation.
   Every decision section should state what was given up.
3. **Document the warts.** Unfinished integrations, computed-then-discarded work, and
   unconfigured defaults belong here explicitly — this is where a new hire learns what
   *not* to trust. Never quietly present a known-broken path as working.
4. **No marketing.** No "powerful", "seamless", "blazing". Plain technical prose.
5. **Prefer concrete numbers** — "20 candidates", "512-word chunks", "-8.0 threshold" —
   over "some" and "several".

## Coverage

- Every file in the repo map in `.ai/instructions.md` §2 gets an entry.
- Skip `__init__.py` unless it has real logic.
- Skip generated paths entirely (`frontend/.next/`, `data/`, `*.pyc`).
- Include one entry per `scripts/*.sh`.

## After generating

1. Cross-check every file in §2 of `.ai/instructions.md` has an entry.
2. Cross-check no entry contradicts §8 (Known Gotchas) of `.ai/instructions.md`.
3. Confirm the model table matches `config/models.py`.
4. Confirm endpoint descriptions match `api/*.py`.
