#!/bin/bash
# Patch the Pi telemetry server to:
# - Accept query_rag / query_direct event types with cache_hit field
# - Make the schema permissive (store metadata as JSON blob)
# - Add a /metrics endpoint that returns event breakdowns

set -e
PI="tlayers21@100.80.105.44"

ssh "$PI" "cat > /tmp/telemetry_patch.py" << 'PYEOF'
"""
Idempotent migration for the RAGbase Pi telemetry server.
Run once; safe to re-run.
"""
import sqlite3
import os

DB_PATH = os.path.expanduser("~/telemetry/telemetry.db")
conn = sqlite3.connect(DB_PATH)

# Ensure the events table can hold arbitrary metadata as JSON text.
# The column may already exist — ignore the error if so.
try:
    conn.execute("ALTER TABLE events ADD COLUMN metadata TEXT DEFAULT '{}'")
    conn.commit()
    print("Added metadata column")
except sqlite3.OperationalError:
    print("metadata column already exists — skipping")

conn.close()
print("Migration complete.")
PYEOF

ssh "$PI" "python3 /tmp/telemetry_patch.py"

# Push the updated main.py that accepts arbitrary fields
ssh "$PI" "cat > /tmp/new_main.py" << 'FASTAPI_EOF'
"""
RAGbase Pi telemetry server — permissive version.
Accepts any event_type and stores metadata as a JSON blob.
Adds /metrics endpoint for metrics.sh breakdowns.
"""
import json
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel

DB_PATH = Path.home() / "telemetry" / "telemetry.db"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            user_id TEXT NOT NULL DEFAULT 'unknown',
            metadata TEXT NOT NULL DEFAULT '{}',
            ts TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(lifespan=lifespan)


class TelemetryEvent(BaseModel):
    event_type: str
    user_id: str = "unknown"
    metadata: dict = {}

    class Config:
        extra = "allow"  # Accept unknown top-level fields without error


@app.post("/telemetry")
def receive(event: TelemetryEvent):
    conn = get_db()
    conn.execute(
        "INSERT INTO events (event_type, user_id, metadata, ts) VALUES (?, ?, ?, ?)",
        (event.event_type, event.user_id, json.dumps(event.metadata), datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()
    return {"status": "ok"}


@app.get("/metrics")
def metrics():
    conn = get_db()
    rows = conn.execute(
        "SELECT event_type, user_id, metadata, ts FROM events ORDER BY id DESC LIMIT 1000"
    ).fetchall()
    conn.close()

    events = [
        {
            "event_type": r["event_type"],
            "user_id": r["user_id"],
            "metadata": json.loads(r["metadata"] or "{}"),
            "ts": r["ts"],
        }
        for r in rows
    ]

    # Summary counts by event type
    counts: dict = {}
    for e in events:
        counts[e["event_type"]] = counts.get(e["event_type"], 0) + 1

    return {"counts": counts, "events": events}
FASTAPI_EOF

# Backup old main.py and put the new one in place
ssh "$PI" "cp ~/telemetry/main.py ~/telemetry/main.py.bak && cp /tmp/new_main.py ~/telemetry/main.py"
echo "Updated ~/telemetry/main.py (backup at ~/telemetry/main.py.bak)"

# Restart the telemetry service if it's managed by systemd
ssh "$PI" "systemctl --user restart telemetry 2>/dev/null || echo 'No systemd unit — restart the server manually'"
echo "Done. Pi telemetry server updated."
