# RAGbase Update-README Skill

## What Triggers a README Update

- New major feature shipped (new ingestor type, new query mode, new UI panel)
- Hardware requirement changed (new model pulled, new dependency)
- Model stack changed (model added, removed, or swapped)
- New script added to `scripts/`
- Installation steps changed in `scripts/install.sh`
- Architecture changed significantly (new service, removed component)

Do NOT update README for: internal refactors, bug fixes, config constant tweaks, or anything not visible to a first-time user.

---

## README Sections

The current README (`README.md`) has these sections, in order:

| Section | What it covers |
|---------|---------------|
| Header / tagline / screenshot | Project name, one-line pitch, `docs/screenshot.png` |
| What it does | One-paragraph pitch — personal AI knowledge base, local-only, no cloud APIs |
| Features | Bullet list of user-visible capabilities |
| Requirements | OS, Ollama, Python, Node.js versions |
| Setup | Numbered steps (install Ollama → Python → Node → clone+install → start), using `scripts/install.sh` |
| Updating | `git pull` + `scripts/start.sh` (which self-updates) |
| How it works | One paragraph: FastAPI + ChromaDB + SQLite graph + Next.js + Ollama, no Docker |
| Model stack | Table: task → model, plus total footprint |
| Hardware | Apple Silicon recommendation, RAM guidance |
| Privacy | Telemetry explanation |
| Resetting | `scripts/reset_all.sh` |
| Directory structure | Top-level tree with one-line comments |
| License | MIT |

There is no "Configuration" or "Roadmap" section in the current README — do not add one unless
the user explicitly asks for it.

---

## Before Editing

1. Read the current README top to bottom.
2. Cross-check the **Model stack** table against `config/models.py` — they must match exactly.
3. Cross-check **Requirements**/**Setup** against the prereq checks in `scripts/install.sh`
   (note: `install.sh` checks for Python 3.11+, but `pyproject.toml` requires `>=3.13` — if you
   touch this section, flag rather than silently resolving the discrepancy).
4. Cross-check the **Directory structure** section against the actual top-level layout.

---

## Tone and Style

- Clear and technical but approachable. Explain abbreviations on first use.
- Second person ("you") for instructions.
- Present tense for descriptions ("RAGbase runs entirely on your Mac").
- Use code blocks for all commands, file paths, and config values.
- No marketing language — no "blazing fast", "revolutionary", "seamless".

---

## What NOT to Change

- **License section** — MIT, text verbatim.
- **Privacy section** — wording around telemetry must be accurate; only `device_id` is sent, never user content. Do not soften or strengthen this claim without verifying `utils/telemetry.py`.
- **GitHub URL** — `github.com/tlayers21/ragbase`.

---

## After Editing

- Verify all `bash` code blocks are valid shell commands.
- Verify the Model stack table matches `config/models.py`.
- Verify Requirements/Setup match `scripts/install.sh` prereq checks.
- Verify the Directory structure section matches the actual top-level layout.
