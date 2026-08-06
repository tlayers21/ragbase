# FastAPI — RAGbase Reference

> Fetched via Context7 — 2026-08-06
> Version: 0.126.0 (per pyproject.toml: fastapi>=0.100.0)
> Re-fetch when version changes or docs feel stale

---

## App Setup & Lifespan

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup: runs once before the app starts receiving requests
    # ideal for shared resources: DB pools, ML model warmup, background workers
    yield
    # shutdown: runs once after the app finishes handling requests

app = FastAPI(lifespan=lifespan)
```

---

## Routers

```python
from fastapi import APIRouter

router = APIRouter(prefix="/ingest", tags=["ingest"])

@router.post("/file")
async def ingest_file(...): ...

# main.py
app.include_router(router)
```

---

## Request Body Types

```python
from fastapi import Form, File, UploadFile
from pydantic import BaseModel

# JSON body
class QueryRequest(BaseModel):
    question: str
    history: list[dict]
    source_filter: list[str] | None = None

@app.post("/query")
async def query(body: QueryRequest): ...

# Multipart form
@app.post("/ingest/file")
async def ingest_file(
    file: UploadFile = File(...),
    source: str = Form(...),
): ...

# Multiple files
@app.post("/uploadfiles/")
async def create_upload_files(files: list[UploadFile]):
    return {"filenames": [file.filename for file in files]}
```

**Note**: File/Form parameters cannot be mixed with a JSON `Body` model in the same request — multipart/form-data encoding doesn't support it. This is why endpoints needing both files and structured data (e.g. `/query/with_attachments`) pass JSON-shaped fields as `Form(...)` strings and `json.loads()` them manually:

```python
@app.post("/query/with_attachments")
async def query_with_attachments(
    question: str = Form(...),
    history: str = Form(...),        # JSON string, decoded with json.loads()
    source_filter: str = Form(default="null"),
    is_direct: bool = Form(default=False),
    attachments: list[UploadFile] = File(default=[]),
): ...
```

---

## Server-Sent Events (SSE)

### Approach 1: Native SSE (`fastapi.sse`, newer FastAPI versions)

```python
from collections.abc import AsyncIterable
from fastapi.sse import EventSourceResponse, ServerSentEvent

@app.post("/query/stream", response_class=EventSourceResponse)
async def stream_query(body: QueryRequest) -> AsyncIterable[ServerSentEvent]:
    yield ServerSentEvent(comment="starting")    # comment field: not sent to client
    async for token in generate_tokens():
        yield ServerSentEvent(data=token, event="token")
    yield ServerSentEvent(raw_data="[DONE]", event="done")
```

**ServerSentEvent fields:**
- `data` — JSON-encoded value (Pydantic models supported)
- `event` — custom event type name (client listens with `addEventListener`)
- `id` — event ID for `Last-Event-ID` resumption
- `retry` — ms before client retries on disconnect
- `raw_data` — pre-formatted string, mutually exclusive with `data`
- `comment` — server-side note, NOT sent to client

Resuming a dropped connection: the browser automatically re-sends the last event ID in a `Last-Event-ID` header on reconnect, which can be read as a route parameter to resume the stream from where it left off:

```python
from typing import Annotated
from fastapi import Header

@app.get("/items/stream", response_class=EventSourceResponse)
async def stream_items(
    last_event_id: Annotated[int | None, Header()] = None,
) -> AsyncIterable[ServerSentEvent]:
    start = last_event_id + 1 if last_event_id is not None else 0
    ...
```

### Approach 2: StreamingResponse (RAGbase current pattern)

```python
from fastapi import Request
from fastapi.responses import StreamingResponse

@app.post("/query/stream")
async def query_stream(body: QueryRequest, request: Request):
    async def event_generator():
        if await request.is_disconnected():
            return
        async for token in generate_stream(...):
            yield f"data: {token}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

---

## Client Disconnect Detection

```python
from fastapi import Request

async def is_disconnected(self) -> bool: ...  # Request.is_disconnected — async, must be awaited
```

```python
@app.post("/query/stream")
async def stream(request: Request, body: QueryRequest):
    async def generator():
        for step in expensive_steps:
            if await request.is_disconnected():   # True = client gone
                return
            result = await process_step(step)
            yield f"data: {result}\n\n"
    ...
```

---

## Request Object

```python
from fastapi import Request

# Available properties
request.method         # "GET", "POST", etc.
request.url            # full URL
request.headers        # headers dict
request.query_params   # URL query params
request.path_params    # path params from route
request.client         # (host, port) tuple or None
request.cookies        # cookies dict

# Async methods — must await
body = await request.body()     # bytes
form = await request.form()     # FormData
json = await request.json()     # parsed JSON
disconnected = await request.is_disconnected()  # bool
```

---

## CORS Middleware

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_origin_regex=r"http://localhost:\d+",  # any localhost port
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Full `CORSMiddleware` signature:

```python
CORSMiddleware(
    app: ASGIApp,
    allow_origins: Sequence[str] = (),
    allow_methods: Sequence[str] = ("GET",),
    allow_headers: Sequence[str] = (),
    allow_credentials: bool = False,
    allow_origin_regex: str | None = None,
    allow_private_network: bool = False,
    expose_headers: Sequence[str] = (),
    max_age: int = 600,
)
```

**Important**: wildcard `["*"]` for origins/methods/headers cannot be combined with `allow_credentials=True` — must list them explicitly (or rely on `allow_origin_regex` for origins).

---

## Response Types

```python
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse, Response

# Serve a file
return FileResponse(path, media_type="application/pdf", filename="doc.pdf")

# Support GET + HEAD on same route
@app.api_route("/sources/{source}/file", methods=["GET", "HEAD"])
async def serve_file(source: str, request: Request):
    if request.method == "HEAD":
        return Response(headers={"Content-Length": str(size)})
    return FileResponse(path)

# HTTP exceptions
from fastapi import HTTPException
raise HTTPException(status_code=404, detail="Source not found")
```

---

## RAGbase-Specific Notes

- Lifespan (`main.py`) is used for reranker warmup and starting the ingestion + graph-build queue workers.
- RAGbase's current streaming pattern is `StreamingResponse` with manual `data: ...\n\n` formatting (Approach 2 above), not the native `fastapi.sse` module.
- `request.is_disconnected()` is checked before each attachment and before generation in `/query/with_attachments`, and before each expensive blocking step in `/query/stream`, so clicking Stop actually halts backend work.
- CORS: `CORSMiddleware` allows `http://localhost:3000` plus any `http://localhost:<port>` via `allow_origin_regex` (dev server may fall back to another port). Needs updating for deployment.
- RAGbase SSE event format used across `/query/stream`, `/query/with_attachments`:
  ```
  data: {token}\n\n
  data: [STAGE]{"stage": "retrieving_sources|traversing_graph|reranking|generating|processing_attachments"}\n\n
  data: [SOURCES]{json_array}\n\n
  data: [ATTACHMENTS]{"attachments": [{"type", "name", "description"}]}\n\n
  data: [HEARTBEAT]\n\n
  data: [DONE]\n\n
  ```
  Heartbeat events are emitted during long blocking Ollama calls (vision, generation) to prevent proxy timeout killing the SSE connection.
- `/sources/{source}/file` supports both GET and HEAD via `@app.api_route(..., methods=["GET", "HEAD"])`, since the Sources modal does a HEAD request per card to sniff content-type before rendering a preview.
