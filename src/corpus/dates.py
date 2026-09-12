"""
Date handling. Every stored date is a timezone-aware UTC datetime, so
"documents from the last 7 days" is one range query.
"""

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Dict, Optional


def parse_datetime(value) -> Optional[datetime]:
    """RFC-2822 ("Thu, 13 Nov 2025 15:02:11 +0000"), ISO 8601 (with or
    without Z), unix seconds, or a datetime. None if unparseable."""
    if value is None or value == '':
        return None

    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        try:
            dt = datetime.fromtimestamp(value, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    elif isinstance(value, str):
        text = value.strip()
        dt = None
        try:
            dt = datetime.fromisoformat(text.replace('Z', '+00:00'))
        except ValueError:
            try:
                dt = parsedate_to_datetime(text)
            except (TypeError, ValueError, IndexError):
                return None
        if dt is None:
            return None
    else:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def event_at_for(doc: Dict, doc_type: str) -> Optional[datetime]:
    """
    When the thing the document describes happened. None when the source
    gives no date — it must never fall back to when we first saw it, or a
    backfilled 2019 company would show up as "new this week".
    """
    if doc_type == 'article':
        return parse_datetime(doc.get('published_date') or doc.get('published_at'))
    if doc_type == 'repo':
        return parse_datetime(doc.get('created_at'))
    if doc_type == 'startup':
        return parse_datetime(doc.get('launched_at'))
    if doc_type == 'launch':
        return parse_datetime(doc.get('launched_at'))
    if doc_type == 'model':
        return parse_datetime(doc.get('created_at'))
    if doc_type == 'paper':
        return parse_datetime(doc.get('published_at'))
    return parse_datetime(doc.get('event_at'))


def first_seen_for(doc: Dict) -> datetime:
    """When we first stored it. Existing rows carry inserted_at or
    scraped_at; new rows get now."""
    return (parse_datetime(doc.get('first_seen_at'))
            or parse_datetime(doc.get('inserted_at'))
            or parse_datetime(doc.get('scraped_at'))
            or datetime.now(timezone.utc))
