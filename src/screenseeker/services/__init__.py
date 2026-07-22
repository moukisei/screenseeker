"""
Use-case layer.

Everything in here takes a Session as its first argument, returns Pydantic
models rather than ORM instances, and never writes to a terminal. Both the CLI
and the web layer are thin callers of these functions.
"""

from .models import WatchResult
from .watch import find_watch_options, parse_query

__all__ = [
    "WatchResult",
    "find_watch_options",
    "parse_query",
]
