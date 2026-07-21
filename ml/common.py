from typing import Any


def to_chunk_index(value: Any) -> int | None:
    """Normalize chunk index values from JSON/metadata into int for comparison."""
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None
