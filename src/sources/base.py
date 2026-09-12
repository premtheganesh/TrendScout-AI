"""
The contract every source implements.

    fetch(since)     -> raw items          (network; not unit-tested)
    normalize(raw)   -> document or None   (pure; tested on saved fixtures)

A source knows nothing about MongoDB, keys or hashes. The ingest runner
adds `type`, `source`, `doc_key`, `event_at` and `content_hash`, then
upserts. Keeping the split strict is what lets every source's parsing be
tested offline with sockets disabled.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Optional


class Source(ABC):
    name: str = ''               # 'yc_oss', 'techcrunch_ai', ...
    doc_type: str = ''           # a name from src/corpus/types.py
    source_tag: str = ''         # stored in doc['source']
    schedule: str = 'weekly'     # 'daily' | 'weekly' | 'monthly'
    default_window_days: Optional[int] = 7   # None = the source has no time axis

    def default_since(self, now: Optional[datetime] = None) -> Optional[datetime]:
        if self.default_window_days is None:
            return None
        now = now or datetime.now(timezone.utc)
        return now - timedelta(days=self.default_window_days)

    @abstractmethod
    def fetch(self, since: Optional[datetime]) -> Iterable[Any]:
        """Yield raw items. `since` is a UTC datetime or None for 'everything'."""

    @abstractmethod
    def normalize(self, raw: Any) -> Optional[Dict[str, Any]]:
        """Turn one raw item into a document dict, or None to skip it.
        Must not include `type`, `source`, `doc_key`, `content_hash` or the
        seen timestamps — the runner owns those."""

    def is_duplicate(self, doc: Dict[str, Any], db) -> bool:
        """Cross-source duplicate check, after identity is attached. The
        default trusts doc_key alone; aggregators that relay other outlets'
        stories override this."""
        return False

    def __repr__(self) -> str:
        return f"<Source {self.name} type={self.doc_type} schedule={self.schedule}>"
