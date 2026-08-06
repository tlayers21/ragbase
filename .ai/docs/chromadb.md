# ChromaDB — RAGbase Reference

> Fetched via Context7 — 2026-08-06
> Version: 1.5.9 (per pyproject.toml: chromadb>=1.0.0)
> Re-fetch when version changes or docs feel stale

---

## Client Setup

```python
import chromadb
from chromadb.config import DEFAULT_TENANT, DEFAULT_DATABASE, Settings

# Embedded persistent client — no server, no Docker
client = chromadb.PersistentClient(
    path="data/chromadb/",
    settings=Settings(),
    tenant=DEFAULT_TENANT,
    database=DEFAULT_DATABASE,
)

# In-memory (ephemeral, for testing only)
client = chromadb.EphemeralClient()

# HTTP client (not used in RAGbase)
client = chromadb.HttpClient(host="localhost", port=8000)
```

---

## Collections

```python
# Get or create (idempotent — use this almost always)
collection = client.get_or_create_collection(
    name="user123",
    metadata={"hnsw:space": "cosine"},   # distance metric: cosine | l2 | ip
)

# Create only (raises if exists)
collection = client.create_collection(name="user123")

# Get existing (raises if not found)
collection = client.get_collection(name="user123")

# Delete
client.delete_collection(name="user123")

# List all
client.list_collections()

# Count documents
n = collection.count()
```

---

## add() / upsert()

```python
collection.add(
    ids=["chunk_001", "chunk_002"],               # required; must be unique strings
    embeddings=[[0.1, 0.2, ...], [0.3, 0.4, ...]],  # pre-computed vectors
    documents=["chunk text 1", "chunk text 2"],   # optional text
    metadatas=[
        {"source": "my_doc", "page": 1},
        {"source": "my_doc", "page": 2},
    ],
)

# upsert: insert or overwrite
collection.upsert(
    ids=["doc-1", "doc-2"],
    documents=["...", "..."],
    metadatas=[{"topic": "basics"}, {"topic": "search"}],
)
```

**add() constraint**: if an ID already exists, the record is silently ignored (no error, no overwrite). Use `upsert()` to overwrite.

All embeddings in a collection must share the same dimensionality — mixing dimensions raises.

Metadata value types allowed: `str`, `int`, `float`, `bool`, and uniform-type arrays of those. Empty arrays are prohibited.

---

## query()

```python
results = collection.query(
    query_embeddings=[[0.1, 0.2, ...]],     # pre-computed — RAGbase always uses this
    # query_texts=["..."],                   # alternative: let Chroma embed
    n_results=20,                            # default: 10
    where={"source": "my_doc"},             # metadata filter
    where_document={"$contains": "keyword"},# full-text filter
    ids=["id1", "id2"],                     # constrain search to these IDs
    include=["documents", "metadatas", "distances", "embeddings"],
)
# Result shape (column-major, per query):
# results["ids"][0]        — list of matching IDs for first query
# results["documents"][0]  — list of matching texts
# results["metadatas"][0]  — list of metadata dicts
# results["distances"][0]  — list of distances (lower = more similar for cosine)
```

`include` default for query: `["documents", "metadatas", "distances"]`

---

## get()

```python
# By IDs
result = collection.get(
    ids=["chunk_001", "chunk_002"],
    include=["documents", "metadatas"],
)

# By filter + pagination
result = collection.get(
    where={"source": "my_doc"},
    limit=100,
    offset=0,
)
# Result shape (flat list):
# result["ids"], result["documents"], result["metadatas"]
```

`include` default for get: `["documents", "metadatas"]`

---

## delete() / update()

```python
# Delete by IDs
collection.delete(ids=["chunk_001"])

# Delete by metadata filter
collection.delete(where={"source": "my_doc"})

# Delete by document-content filter
collection.delete(where_document={"$contains": "deprecated"})

# Some client versions return a count of deleted records
deleted = collection.delete(where={"status": "deleted"}, limit=10)["deleted"]

# Update metadata
collection.update(
    ids=["chunk_001"],
    metadatas=[{"source": "my_doc", "fact_checked": True}],
)
```

---

## Where Filter Operators

```python
# Equality (shorthand and explicit)
where={"source": "my_doc"}
where={"source": {"$eq": "my_doc"}}

# Comparison
where={"page": {"$gt": 5}}     # $gt, $gte, $lt, $lte
where={"score": {"$ne": 0}}

# Set membership
where={"source": {"$in": ["doc_a", "doc_b"]}}
where={"source": {"$nin": ["doc_a"]}}

# Logical — REQUIRED for multi-field filters
where={"$and": [
    {"source": {"$eq": "my_doc"}},
    {"page": {"$gt": 2}},
]}
where={"$or": [
    {"source": "doc_a"},
    {"source": "doc_b"},
]}

# Logical operators nest arbitrarily
where={
    "$and": [
        {"metadata_field1": "value1"},
        {"$and": [{"metadata_field2": "value2"}, {"metadata_field3": "value3"}]},
    ]
}
```

**Critical**: `{"field1": x, "field2": y}` does NOT work as an AND. Must use `{"$and": [...]}`.

`where_document` supports the same `$and`/`$or` composition with `$contains`:

```python
where_document={
    "$or": [
        {"$contains": "technology"},
        {"$contains": "keyword"},
    ]
}
```

---

## Distance Interpretation (cosine space)

- 0.0 = identical vectors
- 1.0 = orthogonal
- 2.0 = opposite

---

## Async Usage in FastAPI

ChromaDB's Python client is synchronous. Wrap calls in `asyncio.to_thread()` in async routes:

```python
import asyncio

results = await asyncio.to_thread(
    collection.query,
    query_embeddings=[embedding],
    n_results=5,
)
```

---

## RAGbase-Specific Notes

- RAGbase collections: `user_{user_id}` (chunks) and `user_{user_id}_summaries` (summaries — note the plural suffix).
- BGE-M3 produces **1024-dim** embeddings. When switching embedding models, delete and recreate collections — a dimension mismatch raises an exception.
- RAGbase filters Stage 1 (`search_summaries()`) results where cosine distance > 0.7 (source likely off-topic), falling back to unfiltered results if all sources exceed the threshold.
- All ChromaDB calls in `api/documents.py` are wrapped in `asyncio.to_thread()` since the client is synchronous.
- Data stored at `data/chromadb/`, no server/Docker needed — `PersistentClient(path="data/chromadb/")`.
