"""
Retrieval evaluation with channel ablations.

Metrics at k: precision, recall, MRR and nDCG. nDCG is the only one that
uses the graded 1/2 relevance labels rather than collapsing them to binary.

Ground truth is data/eval/queries.json.

Run:
    python scripts/evaluate_retrieval.py
    python scripts/evaluate_retrieval.py --k 5 --per-query --sweep
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import json
import math
import logging
import argparse
from typing import Dict, List, Set

from src.corpus.types import COLLECTION
from src.database.mongo_client import MongoDBClient
from src.search.hybrid_search import HybridSearchEngine
from src.search.document_text import document_title

logging.basicConfig(level=logging.WARNING, format='%(levelname)s  %(message)s')
logging.getLogger('src.search.hybrid_search').setLevel(logging.ERROR)

EVAL_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'eval', 'queries.json')

ABLATIONS = [
    ('BM25 only',    {'use_keyword': True,  'use_semantic': False, 'use_graph': False}),
    ('Dense only',   {'use_keyword': False, 'use_semantic': True,  'use_graph': False}),
    ('BM25 + Dense', {'use_keyword': True,  'use_semantic': True,  'use_graph': False}),
    ('+Graph (naive)', {'use_keyword': True, 'use_semantic': True, 'use_graph': True,
                        'graph_expansion_only': False}),
    ('+Graph (recall)', {'use_keyword': True, 'use_semantic': True, 'use_graph': True,
                         'graph_expansion_only': True}),
]


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def precision_at_k(retrieved: List[str], relevant: Set[str], k: int) -> float:
    if k == 0:
        return 0.0
    return len([d for d in retrieved[:k] if d in relevant]) / k


def recall_at_k(retrieved: List[str], relevant: Set[str], k: int) -> float:
    if not relevant:
        return 0.0
    return len([d for d in retrieved[:k] if d in relevant]) / len(relevant)


def reciprocal_rank(retrieved: List[str], relevant: Set[str]) -> float:
    for i, doc_id in enumerate(retrieved, start=1):
        if doc_id in relevant:
            return 1.0 / i
    return 0.0


def ndcg_at_k(retrieved: List[str], gains: Dict[str, int], k: int) -> float:
    """DCG = sum of gain(i) / log2(i + 1), normalised by the ideal ordering."""
    dcg = sum(
        gains.get(doc_id, 0) / math.log2(i + 1)
        for i, doc_id in enumerate(retrieved[:k], start=1)
    )
    ideal = sorted(gains.values(), reverse=True)[:k]
    idcg = sum(g / math.log2(i + 1) for i, g in enumerate(ideal, start=1))
    return dcg / idcg if idcg else 0.0


# ---------------------------------------------------------------------------
# Ground-truth resolution
# ---------------------------------------------------------------------------
def build_name_index(mongo) -> Dict[str, str]:
    """Map every document title to its _id."""
    index = {}
    for doc in mongo.db[COLLECTION].find():
        index[document_title(doc, doc.get('type'))] = str(doc['_id'])
    return index


def resolve(queries: List[Dict], name_index: Dict[str, str]) -> List[Dict]:
    """
    Turn labelled names into doc_ids.

    A name that no longer resolves means the corpus changed under the
    evaluation set — silently dropping it would quietly inflate every
    score, so this reports and refuses to average over broken labels.
    """
    resolved, missing = [], []

    for query in queries:
        gains = {}
        for name, gain in query['relevant'].items():
            doc_id = name_index.get(name)
            if doc_id is None:
                missing.append((query['id'], name))
                continue
            gains[doc_id] = gain
        resolved.append({**query, 'gains': gains})

    if missing:
        print("\n  WARNING — labels that no longer match any document:")
        for query_id, name in missing:
            print(f"    {query_id}: {name!r}")
        print("  Fix data/eval/queries.json or rebuild the corpus.\n")

    return resolved


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------
def evaluate(engine, queries: List[Dict], flags: Dict, k: int) -> Dict:
    totals = {'p': 0.0, 'r': 0.0, 'mrr': 0.0, 'ndcg': 0.0}
    per_query = []

    for query in queries:
        gains = query['gains']
        if not gains:
            continue

        results = engine.search(query['query'], top_k=k, **flags)
        retrieved = [r['doc_id'] for r in results]
        relevant = set(gains)

        scores = {
            'p': precision_at_k(retrieved, relevant, k),
            'r': recall_at_k(retrieved, relevant, k),
            'mrr': reciprocal_rank(retrieved, relevant),
            'ndcg': ndcg_at_k(retrieved, gains, k),
        }
        for key in totals:
            totals[key] += scores[key]
        per_query.append({'id': query['id'], 'query': query['query'],
                          'type': query.get('type', ''), **scores})

    n = len(per_query) or 1
    return {
        'mean': {key: value / n for key, value in totals.items()},
        'per_query': per_query,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--k', type=int, default=10, help='cut-off (default 10)')
    parser.add_argument('--per-query', action='store_true',
                        help='print a per-query breakdown of the full system')
    parser.add_argument('--sweep', action='store_true',
                        help='sweep the BM25 fusion weight and report nDCG')
    args = parser.parse_args()

    print("=" * 78)
    print(f"TRENDSCOUT AI — RETRIEVAL EVALUATION  (k = {args.k})")
    print("=" * 78)

    with open(os.path.abspath(EVAL_PATH)) as f:
        spec = json.load(f)

    mongo = MongoDBClient()
    queries = resolve(spec['queries'], build_name_index(mongo))
    judged = sum(len(q['gains']) for q in queries)
    print(f"\n{len(queries)} queries · {judged} relevance judgements\n")

    engine = HybridSearchEngine()

    results = {}
    header = f"{'Configuration':<18}{'P@k':>9}{'R@k':>9}{'MRR':>9}{'nDCG@k':>9}"
    print(header)
    print("-" * len(header))

    for name, flags in ABLATIONS:
        outcome = evaluate(engine, queries, flags, args.k)
        results[name] = outcome
        m = outcome['mean']
        print(f"{name:<18}{m['p']:>9.3f}{m['r']:>9.3f}{m['mrr']:>9.3f}{m['ndcg']:>9.3f}")

    print("\n" + "=" * 78)
    print("WHAT EACH CHANNEL ADDS  (nDCG@k)")
    print("=" * 78)

    def ndcg(name):
        return results[name]['mean']['ndcg']

    def delta(label, better, worse):
        base = ndcg(worse)
        gain = ndcg(better) - base
        pct = (gain / base * 100) if base else float('nan')
        print(f"  {label:<44} {gain:+.3f}  ({pct:+.1f}%)")

    delta("Fusing dense into BM25", 'BM25 + Dense', 'BM25 only')
    delta("Fusing BM25 into dense", 'BM25 + Dense', 'Dense only')
    delta("Adding the graph channel, naive fusion", '+Graph (naive)', 'BM25 + Dense')
    delta("Adding the graph channel, recall-only", '+Graph (recall)', 'BM25 + Dense')

    print("\n" + "=" * 78)
    print("BY QUERY TYPE  (nDCG@k)")
    print("=" * 78)
    print(f"{'Configuration':<18}{'lexical':>10}{'semantic':>10}")
    print("-" * 38)
    for name, _ in ABLATIONS:
        rows = results[name]['per_query']
        by_type = {}
        for query_type in ('lexical', 'semantic'):
            subset = [r['ndcg'] for r in rows if r['type'] == query_type]
            by_type[query_type] = sum(subset) / len(subset) if subset else 0.0
        print(f"{name:<18}{by_type['lexical']:>10.3f}{by_type['semantic']:>10.3f}")

    if args.sweep:
        print("\n" + "=" * 78)
        print("FUSION WEIGHT SWEEP  (BM25 weight, dense fixed at 1.0)")
        print("=" * 78)
        print(f"{'bm25 weight':<14}{'nDCG@k':>9}{'lexical':>10}{'semantic':>10}")
        print("-" * 43)
        original = dict(engine.weights)
        for weight in (0.0, 0.25, 0.5, 0.75, 1.0):
            engine.weights = {**original, 'keyword': weight}
            rows = evaluate(engine, queries, ABLATIONS[-1][1], args.k)['per_query']
            overall = sum(r['ndcg'] for r in rows) / len(rows)
            by_type = {}
            for query_type in ('lexical', 'semantic'):
                subset = [r['ndcg'] for r in rows if r['type'] == query_type]
                by_type[query_type] = sum(subset) / len(subset) if subset else 0.0
            print(f"{weight:<14.2f}{overall:>9.3f}"
                  f"{by_type['lexical']:>10.3f}{by_type['semantic']:>10.3f}")
        engine.weights = original
        print("\n  Differences under ~0.01 are noise on a 22-query set.")

    if args.per_query:
        print("\n" + "=" * 78)
        print("PER-QUERY  (BM25 + dense + graph recall)")
        print("=" * 78)
        print(f"{'id':<5}{'type':<10}{'nDCG':>7}{'P@k':>7}{'R@k':>7}  query")
        print("-" * 78)
        for row in results['+Graph (recall)']['per_query']:
            print(f"{row['id']:<5}{row['type']:<10}{row['ndcg']:>7.3f}"
                  f"{row['p']:>7.3f}{row['r']:>7.3f}  {row['query'][:38]}")

    engine.close()
    mongo.close()
    print("\n" + "=" * 78)


if __name__ == "__main__":
    main()
