"""
Process what changed since the last run.

    python scripts/run_pipeline.py                       # every stage, incremental
    python scripts/run_pipeline.py --stages embed,index  # some stages
    python scripts/run_pipeline.py --force               # redo everything
    python scripts/run_pipeline.py --neo4j-fresh         # clear the graph first

Stages: refresh, entities, embed, index, snapshots, neo4j. A row is written
to `runs` (source = "pipeline") with per-stage results.
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import argparse
import logging

from src.config import get_settings
from src.database.mongo_client import MongoDBClient
from src.pipeline.run import DEFAULT_STAGES, STAGES, Pipeline

logging.basicConfig(level=logging.WARNING, format='%(levelname)s  %(message)s')
logging.getLogger('src.pipeline').setLevel(logging.INFO)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--stages', default=','.join(DEFAULT_STAGES),
                        help=f"comma-separated subset of {','.join(STAGES)}")
    parser.add_argument('--force', action='store_true', help='treat every document as stale')
    parser.add_argument('--neo4j-fresh', action='store_true', help='clear Neo4j before syncing')
    args = parser.parse_args()

    stages = [s.strip() for s in args.stages.split(',') if s.strip()]
    unknown = [s for s in stages if s not in STAGES]
    if unknown:
        raise SystemExit(f"unknown stage(s) {unknown}; choose from {list(STAGES)}")

    mongo = MongoDBClient()
    settings = get_settings()
    print("=" * 72)
    print(f"PIPELINE  database={mongo.db_name}  index_dir={settings.index_dir}"
          + ("  [FORCE]" if args.force else ""))
    print("=" * 72)

    pipeline = Pipeline(mongo.db)
    if args.neo4j_fresh:
        from src.pipeline.graph import sync_graph
        pipeline.run_stage = _with_fresh_neo4j(pipeline.run_stage, sync_graph, mongo.db)

    record = pipeline.run(stages, force=args.force)
    for stage, result in record['results'].items():
        shown = {k: v for k, v in result.items() if k != 'seconds'}
        print(f"  {stage:<10} {result.get('seconds', 0):>6}s  {shown}")
    print("-" * 72)
    print(f"  {record['status'].upper()} in {record['duration_s']}s"
          + (f"  — {record['error']}" if record.get('error') else ""))
    mongo.close()
    sys.exit(0 if record['status'] == 'ok' else 1)


def _with_fresh_neo4j(run_stage, sync_graph, db):
    def wrapped(stage, force=False):
        if stage == 'neo4j':
            summary = sync_graph(db, fresh=True)
            return summary if summary is not None else {'skipped': 'neo4j unreachable'}
        return run_stage(stage, force=force)
    return wrapped


if __name__ == '__main__':
    main()
