"""
Reciprocal Rank Fusion arithmetic.

    score(d) = sum over channels c of  weight[c] / (k + rank[c](d))
"""

import pytest

from src.search.hybrid_search import HybridSearchEngine, RRF_K


class StubEngine:
    """Exercises the fusion method without loading models or MongoDB."""
    def __init__(self, weights=None):
        self.weights = weights or {'keyword': 1.0, 'semantic': 1.0, 'graph': 0.5}

    reciprocal_rank_fusion = HybridSearchEngine.reciprocal_rank_fusion


def hit(doc_id, collection='startups', score=1.0, **extra):
    return {'doc_id': doc_id, 'collection': collection, 'score': score, **extra}


class TestRRF:
    def test_matches_the_formula(self):
        fused = StubEngine().reciprocal_rank_fusion({'keyword': [hit('a')]})
        assert fused[0]['rrf_score'] == pytest.approx(1.0 / (RRF_K + 1))

    def test_agreement_between_channels_outranks_a_single_first_place(self):
        fused = StubEngine().reciprocal_rank_fusion({
            'keyword': [hit('solo'), hit('both')],
            'semantic': [hit('other'), hit('both')],
        })
        assert fused[0]['doc_id'] == 'both'

    def test_score_accumulates_across_channels(self):
        fused = StubEngine().reciprocal_rank_fusion({
            'keyword': [hit('x')],
            'semantic': [hit('x')],
        })
        expected = 2 * (1.0 / (RRF_K + 1))
        assert fused[0]['rrf_score'] == pytest.approx(expected)

    def test_weights_are_applied(self):
        fused = StubEngine(weights={'keyword': 1.0, 'graph': 0.5}
                           ).reciprocal_rank_fusion({'graph': [hit('g')]})
        assert fused[0]['rrf_score'] == pytest.approx(0.5 / (RRF_K + 1))

    def test_graph_channel_cannot_outvote_agreement(self):
        # Graph hits are second-hand — derived from what the other channels
        # already found — so a graph-only document must not beat one that
        # both primary channels ranked.
        fused = StubEngine().reciprocal_rank_fusion({
            'keyword': [hit('real')],
            'semantic': [hit('real')],
            'graph': [hit('derived')],
        })
        assert fused[0]['doc_id'] == 'real'

    def test_results_are_sorted_descending(self):
        fused = StubEngine().reciprocal_rank_fusion({
            'keyword': [hit('a'), hit('b'), hit('c')],
        })
        scores = [f['rrf_score'] for f in fused]
        assert scores == sorted(scores, reverse=True)

    def test_ranks_are_recorded_for_explainability(self):
        fused = StubEngine().reciprocal_rank_fusion({
            'keyword': [hit('x'), hit('y')],
            'semantic': [hit('y')],
        })
        by_id = {f['doc_id']: f for f in fused}
        assert by_id['y']['ranks'] == {'keyword': 2, 'semantic': 1}
        assert by_id['x']['ranks'] == {'keyword': 1}

    def test_channel_scores_are_preserved(self):
        fused = StubEngine().reciprocal_rank_fusion({
            'keyword': [hit('x', score=7.5)],
        })
        assert fused[0]['channel_scores']['keyword'] == 7.5

    def test_shared_entities_survive_fusion(self):
        fused = StubEngine().reciprocal_rank_fusion({
            'graph': [hit('x', shared_entities=['OpenAI'])],
        })
        assert fused[0]['shared_entities'] == ['OpenAI']

    def test_collection_recovered_from_any_channel(self):
        fused = StubEngine().reciprocal_rank_fusion({
            'graph': [hit('x', collection='')],
            'keyword': [hit('x', collection='articles')],
        })
        assert fused[0]['collection'] == 'articles'

    def test_empty_input(self):
        assert StubEngine().reciprocal_rank_fusion({}) == []

    def test_empty_channels_are_harmless(self):
        fused = StubEngine().reciprocal_rank_fusion({
            'keyword': [], 'semantic': [hit('a')], 'graph': [],
        })
        assert len(fused) == 1

    def test_lower_rank_scores_higher(self):
        fused = StubEngine().reciprocal_rank_fusion({
            'keyword': [hit('first'), hit('second')],
        })
        assert fused[0]['doc_id'] == 'first'

    def test_k_damps_top_rank_dominance(self):
        """k=60 keeps rank 1 and rank 2 close, so no single channel dominates."""
        r1 = 1 / (RRF_K + 1)
        r2 = 1 / (RRF_K + 2)
        assert r1 / r2 < 1.02
