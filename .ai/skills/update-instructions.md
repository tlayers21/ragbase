# RAGbase Update-Instructions Skill

The canonical project context file is `.ai/instructions.md`.
`.github/copilot-instructions.md` is a one-line pointer to it — never add content there.

---

## What Triggers an Update

| Change | Section to update |
|--------|------------------|
| New file or directory added/removed | Directory Structure |
| New or changed API endpoint | API Endpoints |
| New model added or swapped | Model Stack table |
| New dependency, removed dependency | Known Gotchas (if tricky) |
| New architectural decision | Architecture Rationale |
| New trap discovered during development | Known Gotchas |
| Feature removed | Directory Structure + Known Gotchas + Rationale |
| New frontend component or hook | Directory Structure (frontend subtree) |
| New script in `scripts/` | Directory Structure |

---

## Format Rules

- Match the existing style exactly: same header levels (`##`, `###`), same table format, same code block style.
- Directory structure entries use the tree format with tab-aligned comments — match the indentation of adjacent entries.
- API endpoints section uses plain-text aligned columns — no Markdown table.
- Known Gotchas entries: `**Bold term**` — one-sentence explanation.
- Keep entries terse. If a gotcha needs more than 3 lines, it's probably two gotchas.

---

## Updating the Directory Structure

- Add the file at the correct tree level with a tab-aligned comment matching the style of adjacent entries.
- Removing a file: delete its entry entirely. Do not leave a `(removed)` note.
- If a module's behavior changes significantly, update its inline comment.

---

## Updating the API Endpoints Section

- One endpoint per line: `METHOD /path  description`
- Match the column alignment of adjacent entries.
- If a new SSE event type is added, update the SSE format block at the bottom of the section.

---

## Updating Known Gotchas

- **Never remove an existing gotcha.** They exist because someone got burned. If behavior changes, update the entry — don't delete it.
- Add new gotchas at the end of the relevant gotchas section (Backend or Frontend).
- Format: `- **Term** — explanation.`

---

## After Editing

1. Verify `.github/copilot-instructions.md` still contains only the pointer to `.ai/instructions.md` — it should never have grown content.
2. Verify the Model Stack table matches `config/models.py` exactly.
3. Verify the API Endpoints section matches the routes defined in `api/*.py`.
