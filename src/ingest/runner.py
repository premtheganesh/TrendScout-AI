"""
Run sources and record what happened.

Each source runs inside its own try/except and writes its own row to the
`runs` collection, so one broken feed never stops the others and the
history of every run is queryable:

    db.runs.find({'source': 'techcrunch_ai'}).sort('started_at', -1)
"""

import logging
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from src.ingest.store import DocumentStore, prepare
from src.sources.base import Source

logger = logging.getLogger(__name__)

RUNS_COLLECTION = 'runs'


def run_source(source: Source, db, since: Optional[datetime] = None,
               dry_run: bool = False) -> Dict[str, Any]:
    started = datetime.now(timezone.utc)
    since = since if since is not None else source.default_since(started)
    record: Dict[str, Any] = {
        'source': source.name,
        'type': source.doc_type,
        'since': since,
        'started_at': started,
        'dry_run': dry_run,
        'fetched': 0, 'new': 0, 'changed': 0, 'unchanged': 0, 'skipped': 0,
        'errors': 0,
        'status': 'running',
    }
    store = DocumentStore(db)

    try:
        for raw in source.fetch(since):
            record['fetched'] += 1
            try:
                fields = source.normalize(raw)
            except Exception as e:  # one bad item must not kill the run
                record['errors'] += 1
                logger.warning(f"{source.name}: normalize failed: {e}")
                continue
            if fields is None:
                record['skipped'] += 1
                continue
            try:
                doc = prepare(fields, source.doc_type, source.source_tag)
            except ValueError as e:
                record['errors'] += 1
                logger.warning(f"{source.name}: no identity: {e}")
                continue
            if source.is_duplicate(doc, db):
                record['skipped'] += 1
                continue
            if dry_run:
                record['new'] += 1
                continue
            record[store.upsert(doc, now=started)] += 1
        record['status'] = 'ok'
    except Exception as e:
        record['status'] = 'failed'
        record['error'] = f"{type(e).__name__}: {e}"
        record['traceback'] = traceback.format_exc()[-2000:]
        logger.error(f"{source.name} failed: {record['error']}")

    record['finished_at'] = datetime.now(timezone.utc)
    record['duration_s'] = round((record['finished_at'] - started).total_seconds(), 1)
    if not dry_run:
        db[RUNS_COLLECTION].insert_one(dict(record))
    record.pop('_id', None)
    return record


def run_sources(sources: Iterable[Source], db, since: Optional[datetime] = None,
                dry_run: bool = False) -> List[Dict[str, Any]]:
    return [run_source(s, db, since=since, dry_run=dry_run) for s in sources]


def format_run(record: Dict[str, Any]) -> str:
    status = record['status'].upper()
    line = (f"  {record['source']:<16} {status:<7} fetched={record['fetched']:<5} "
            f"new={record['new']:<5} changed={record['changed']:<4} "
            f"unchanged={record['unchanged']:<5} skipped={record['skipped']:<5} "
            f"errors={record['errors']:<3} {record.get('duration_s', 0):>6}s")
    if record.get('error'):
        line += f"\n      {record['error']}"
    return line
