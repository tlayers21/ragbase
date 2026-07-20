from .compact import router as compact_router
from .documents import router as documents_router
from .ingest import router as ingest_router
from .query import router as query_router
from .sessions import router as sessions_router
from .sources import router as sources_router
from .title import router as title_router

__all__ = [
    "compact_router",
    "ingest_router",
    "query_router",
    "documents_router",
    "sessions_router",
    "sources_router",
    "title_router",
]
