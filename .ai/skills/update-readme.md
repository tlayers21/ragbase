# RAGbase Update-README Skill

`README.md` is the **only** public-facing document. Its audience is someone who has
never seen the project and is deciding whether to run it — not a contributor. Everything
internal belongs in `.ai/instructions.md` or `docs/CODEBASE_EXPLAINED.md` instead.

## Triggers — be specific

Update **only** when something changes that a first-time user would experience:

| Change | Section |
|---|---|
| A new source type can be ingested (e.g. audio files) | Features |
| A new user-visible mode or panel ships | Features |
| A model is added, removed, or swapped in `config/models.py` | Model stack |
| A model's size changes the total download footprint | Model stack, Hardware |
| A prereq version changes in `scripts/install.sh` | Requirements, Setup |
| A new script a user would run is added to `scripts/` | Setup or Resetting |
| A top-level directory is added or removed | Directory structure |
| What telemetry sends changes | Privacy |

**Not triggers:** internal refactors, bug fixes, config constant tweaks, new API
endpoints, new components, anything under `.ai/`. If a user can't see it, it doesn't go
in the README.

## Current sections (in order)

Header/tagline/screenshot · What it does · Features · Requirements · Setup · Updating ·
How it works · Model stack · Hardware · Privacy · Resetting · Directory structure · License

There is no Configuration or Roadmap section. **Do not add one unless asked.**

## Good vs bad edits

**Bad — internal detail a user can't act on:**
> - Retrieval uses reciprocal rank fusion with k=60 over a 20-candidate pool.

**Good — the user-visible capability:**
> - Hybrid keyword + semantic search, so exact terms like error codes still match.

---

**Bad — marketing:**
> RAGbase is a blazing-fast, revolutionary knowledge base that seamlessly unifies all
> your data.

**Good — plain and concrete:**
> RAGbase ingests your notes, PDFs, images and videos, then answers questions about them
> with citations. Everything runs on your own machine.

---

**Bad — a setup step that can't be verified:**
> Install the required dependencies and start the app.

**Good — exact, copy-pasteable, matches `install.sh`:**
> ```bash
> bash scripts/install.sh
> bash scripts/start.sh
> ```

---

**Bad — a model table that drifted from the code:**
> | Answering | llama3.1:8b |

**Good — matches `config/models.py` exactly, with the user-relevant framing:**
> | Answering questions | `qwen3` | 5.2 GB |

## Before editing

1. Read the whole README first.
2. Cross-check the **Model stack** table against `config/models.py` — must match exactly.
   Get sizes from `ollama list`.
3. Cross-check **Requirements**/**Setup** against the prereq checks in
   `scripts/install.sh`. Both it and `pyproject.toml` require Python 3.13+ — if you
   change one, change the other.
4. Cross-check **Directory structure** against the actual top-level layout.

## Tone

Second person for instructions ("you"), present tense for description ("RAGbase runs
entirely on your Mac"). Technical but approachable; expand abbreviations on first use.
Code blocks for every command, path and config value. No marketing adjectives.

## Never change without verifying

- **License** — MIT, verbatim.
- **Privacy** — only `device_id` and event metadata are sent, never `user_id` and never
  user content. Re-read `utils/telemetry.py` before touching a single word here.
- **GitHub URL** — `github.com/tlayers21/ragbase`.

## After editing

- Every `bash` block is a valid, runnable command.
- Model stack table == `config/models.py`.
- Requirements/Setup == `scripts/install.sh`.
- Directory structure == actual top-level layout.
