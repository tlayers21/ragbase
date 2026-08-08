# RAGbase Update-Scripts Skill

Three shell scripts in `scripts/` have to stay in step with a codebase that doesn't
import them. Nothing fails at import time when they drift — `install.sh` produces a
machine that dies on first ingest, `reset_all.sh` leaves state behind that makes the
next run behave like the old one, `start.sh` serves a stale production build. Every
failure surfaces minutes or days later, somewhere else.

| Script | Job |
|---|---|
| `scripts/install.sh` | First-time setup: prerequisites, Ollama models, venv, frontend build |
| `scripts/start.sh` | Update check → backend → conditional frontend build → frontend → browser |
| `scripts/reset_all.sh` | Wipe all runtime state, keep identity and config |

Read `.ai/instructions.md` §11 first for how they're meant to be used.

---

## When to update

| You changed... | Check |
|---|---|
| Added a dependency to `pyproject.toml` | `install.sh` — does it need a **system** package (see below)? |
| Added a `MODEL_*` constant in `config/models.py` | `install.sh` — the `for model in ...` pull loop |
| Added a path to `config/paths.py` | `reset_all.sh` — clear it, or add it to the preserved list |
| Added a file the app writes under `data/` | `reset_all.sh` — including any `-wal`/`-shm` companions |
| Started a new process in `main.py` or a script | `reset_all.sh` kill list, `start.sh` trap |
| Used a new port | `start.sh` and `reset_all.sh` port clearing |
| Bumped `requires-python` | `install.sh` version gate |
| Added a frontend source directory | `start.sh` build-hash inputs |
| New service, database, or daemon | all three |

The trigger is **adding**, not changing. Editing `retrieval/search.py` never touches a
script; adding `data/foo.db` touches two.

---

## The system-dependency trap

This is the one that actually bit. A `pip install` succeeding proves nothing about
whether the package *runs* — several pull in a CLI binary at call time, inside a
lazily-imported function, so the failure lands mid-ingest on a user's first PDF.

Currently required, and checked by `install.sh`:

| Binary | Needed by | Fails at |
|---|---|---|
| `ffmpeg` | `openai-whisper` (`whisper/audio.py` shells out to decode audio), `yt-dlp` | every video and YouTube ingest |
| `pdftoppm` (poppler) | `pdf2image.convert_from_path()` | every scanned/handwritten PDF — the primary path for any PDF without a text layer |

Deliberately **not** required:

- **anydoc** — ships prebuilt `abi3` wheels for macOS (x86_64/arm64) and Linux
  (manylinux + musllinux, x86_64/aarch64). No Rust toolchain, no build tools. Do not
  add a `cargo`/`rustc` check; it would fail installs that work fine.
- **docling, rapidocr, paddleocr, transformers, torch** — pure pip on both supported
  platforms.
- **Docker** — nothing needs it. ChromaDB is embedded (`PersistentClient`), the cache
  and graph are SQLite files, Redis is gone. If a script grows a Docker check,
  something has regressed architecturally.

When adding a dependency, find out whether it calls out to a binary:

```bash
# Does the package shell out?
grep -rn "subprocess\|Popen\|shutil.which" .venv/lib/python3.13/site-packages/<pkg>/ | head
```

---

## Checklist: `install.sh`

- [ ] Pulls every distinct model name in `config/models.py`. Compare against the
      `MODEL_*` constants, not `get_model()`'s keys — several keys share one model.
- [ ] Checks every system binary in the table above, with a per-OS install hint.
- [ ] Python version gate matches `requires-python` in `pyproject.toml`.
- [ ] Creates every directory the app writes into: `data/sources`, `data/chromadb`,
      `logs`. (Each is also created lazily at runtime, so a miss here is a
      permissions-error-at-the-wrong-time bug, not a crash.)
- [ ] Installs from `pyproject.toml` via `uv pip install -e .` — never a hand-maintained
      package list that can drift.
- [ ] Re-pins `huggingface-hub<1.0` *after* the main install (§8: `uv` can move it past
      1.0 and break `transformers`).
- [ ] Frontend `npm install && npm run build`.
- [ ] Smoke-tests that the extractors import and convert, so a missing wheel fails
      during setup rather than at first ingest.
- [ ] No Docker.
- [ ] Success message names the next command.

Verify the model list mechanically:

```bash
grep -oE '^MODEL_[A-Z_]+ = "[^"]+"' config/models.py | sed 's/.*"\(.*\)"/\1/' | sort -u
grep -oE 'for model in [^;]*' scripts/install.sh
```

## Checklist: `reset_all.sh`

- [ ] Clears every path in `config/paths.py` under `DATA_DIR`, except the preserved set.
- [ ] **Preserves** `data/user_id.txt`, `data/device_id.txt` (deleting either orphans
      every ChromaDB collection and graph table — they're interpolated into the names),
      `data/settings.json`, and `data/training_data/` (the user's own corpus).
- [ ] Deletes `-wal` and `-shm` alongside every SQLite file. Both DBs run in WAL mode,
      so removing only the `.db` leaves committed rows that SQLite replays into the
      "fresh" database on next open.
- [ ] Clears glob-named state, not just fixed filenames — `data/*_progress.json` are the
      per-source resume checkpoints for scanned PDFs, and a stale one makes a re-ingest
      resume mid-document instead of starting at page 1.
- [ ] Kills every process `start.sh` starts, plus the dev-loop forms from §11
      (`python3 -m uvicorn`, `npm run dev`) and the `next-server` child that survives
      its `npm` parent.
- [ ] Clears ports 3000 and 8001.
- [ ] Touches `data/reset_sessions_flag` — chat sessions live in `localStorage`, so this
      flag is the only way a backend reset can reach them.
- [ ] `cd`s to the project root first. It runs `rm -rf` on relative paths.

Audit coverage mechanically:

```bash
# Every DATA_DIR path the code knows about, against what the script mentions
grep -oE 'DATA_DIR / "[^"]+"' config/paths.py | sed 's/.*"\(.*\)"/\1/' | sort -u
grep -oE 'data/[^ ]*' scripts/reset_all.sh | sort -u
```

## Checklist: `start.sh`

- [ ] Clears ports 3000 and 8001 before starting.
- [ ] Creates `data/sources`, `data/chromadb`, `logs`.
- [ ] Uses `.venv/bin/python3` for **every** Python call. Bare `python3` and bare
      `uvicorn` resolve to system Python and won't see the venv.
- [ ] Build hash covers every directory holding frontend source *and* the config files
      that change build output — `app`, `components`, `lib`, `hooks`, `types`, `public`,
      plus `package.json`, `next.config.ts`, `tsconfig.json`, `postcss.config.mjs`.
      A missing directory means real changes ship against a stale production build.
- [ ] Hashing is portable: `md5sum` on Linux, `md5` on macOS. `install.sh` supports both.
- [ ] `trap` is registered **immediately after the first background process starts**,
      not at the end. The build and the readiness wait can take minutes, and a Ctrl+C in
      that window must still kill the backend.
- [ ] Cleanup kills `next-server` as well as the `npm start` wrapper that spawned it.
- [ ] Background compound commands use a subshell: `(cd frontend && npm start) &`, never
      `cd frontend && npm start &`. Backgrounding an AND-list leaves the parent shell's
      cwd unchanged, so a following `cd ..` walks the script out of the project root.

---

## Always verify after editing

```bash
bash -n scripts/install.sh   && echo "install.sh syntax OK"
bash -n scripts/start.sh     && echo "start.sh syntax OK"
bash -n scripts/reset_all.sh && echo "reset_all.sh syntax OK"

bash scripts/install.sh --dry-run    # runs every check, changes nothing
```

`bash -n` is a parse check only — it proves nothing about behavior.

- **`install.sh --dry-run`** is the safe way to exercise it. A plain run is destructive
  to the venv (`uv venv --clear`), so always pass the flag when auditing. Keep the flag
  working: any new side-effecting command must go through the `run` helper or an
  explicit `if [[ "$DRY_RUN" -eq 1 ]]` branch, or the dry run silently stops being dry.
- **`reset_all.sh`** deletes real user data. **Never run it to test a change.** Audit it
  statically with the coverage commands above.
- **`start.sh`** does a `git pull` and a production build. Test the pieces (the hash
  function, the trap) in isolation rather than running the whole script.

If a script grows past roughly what fits on a screen, or starts needing arrays and
functions, that is the signal to move the logic into Python under `scripts/` and leave
the shell as a thin wrapper.
