"""Tokenisation and the BM25 index."""

import pytest

from src.search.bm25_index import tokenize, BM25Index, STOPWORDS


class TestTokenize:
    def test_lowercases(self):
        assert tokenize('Suno AI') == ['suno', 'ai']

    def test_removes_stopwords(self):
        tokens = tokenize('the platform for building agents')
        assert 'the' not in tokens
        assert 'for' not in tokens
        assert 'platform' in tokens

    def test_preserves_domain_punctuation(self):
        assert 'c++' in tokenize('written in c++')
        assert 'gpt-4' in tokenize('powered by gpt-4')
        assert 'node.js' in tokenize('built on node.js')

    def test_drops_single_characters(self):
        assert tokenize('a b ai') == ['ai']

    def test_empty_input(self):
        assert tokenize('') == []
        assert tokenize(None) == []

    def test_punctuation_only_is_dropped(self):
        assert tokenize('!!! ??? ...') == []

    def test_stopword_list_is_conservative(self):
        for term in ('ai', 'data', 'open', 'source'):
            assert term not in STOPWORDS


class FakeCollection:
    def __init__(self, docs):
        self._docs = docs

    def find(self, *args, **kwargs):
        return iter(self._docs)


class FakeMongo:
    """Documents of every type live in one collection, tagged by `type`."""
    def __init__(self, data):
        docs = [{**doc, 'type': doc_type}
                for doc_type, group in data.items() for doc in group]
        self.db = {'documents': FakeCollection(docs)}


@pytest.fixture
def index():
    """
    Okapi IDF is log((N - n + 0.5) / (n + 0.5)), which is zero when a term
    appears in half the corpus. Ten documents keeps these tests measuring
    ranking rather than a degenerate IDF.
    """
    mongo = FakeMongo({
        'startup': [
            {'_id': 's1', 'name': 'Suno',
             'description': 'AI music generation platform',
             'location': 'Cambridge, Massachusetts'},
            {'_id': 's2', 'name': 'Overjet',
             'description': 'Dental artificial intelligence',
             'location': 'Boston, Massachusetts'},
            {'_id': 's3', 'name': 'Abridge',
             'description': 'Clinical documentation for hospitals',
             'location': 'Pittsburgh, Pennsylvania'},
            {'_id': 's4', 'name': 'Harvey',
             'description': 'Legal research assistant for law firms',
             'location': 'San Francisco, California'},
            {'_id': 's5', 'name': 'Cohere',
             'description': 'Enterprise language model provider',
             'location': 'Toronto, Canada'},
        ],
        'article': [
            {'_id': 'a1', 'title': 'Music startup raises funding',
             'description': 'A song generation company raised money'},
            {'_id': 'a2', 'title': 'Chip demand climbs',
             'description': 'Semiconductor supply remains constrained'},
        ],
        'repo': [
            {'_id': 'r1', 'full_name': 'langchain-ai/langchain',
             'description': 'Framework for LLM agents',
             'primary_language': 'Python'},
            {'_id': 'r2', 'full_name': 'pinecone-io/canopy',
             'description': 'Retrieval augmented generation engine',
             'primary_language': 'Python'},
            {'_id': 'r3', 'full_name': 'ggerganov/llama.cpp',
             'description': 'Inference of language models in C++',
             'primary_language': 'C++'},
        ],
    })
    return BM25Index().build(mongo)


class TestBM25Index:
    def test_indexes_every_type(self, index):
        assert len(index) == 10
        assert set(index.types) == {'startup', 'article', 'repo'}

    def test_exact_term_ranks_first(self, index):
        results = index.search('Suno')
        assert results[0]['doc_id'] == 's1'

    def test_scores_are_positive_and_descending(self, index):
        results = index.search('music generation language')
        assert len(results) >= 2
        scores = [r['score'] for r in results]
        assert all(s > 0 for s in scores)
        assert scores == sorted(scores, reverse=True)

    def test_non_matching_documents_are_excluded(self, index):
        results = index.search('Suno')
        assert all(r['score'] > 0 for r in results)
        assert 'r1' not in [r['doc_id'] for r in results]

    def test_type_filter(self, index):
        results = index.search('music startup funding', doc_type='article')
        assert results
        assert all(r['type'] == 'article' for r in results)

    def test_allowed_ids_restricts_before_truncation(self, index):
        results = index.search('music song generation', allowed_ids={'a1'})
        assert [r['doc_id'] for r in results] == ['a1']

    def test_empty_allowed_set_returns_nothing(self, index):
        assert index.search('music', allowed_ids=set()) == []

    def test_top_k_is_respected(self, index):
        assert len(index.search('generation platform language', top_k=1)) <= 1

    def test_ubiquitous_terms_carry_no_signal(self, index):
        """A term with no discriminative power must not create a ranking."""
        assert index.search('python')

    def test_empty_query_returns_nothing(self, index):
        assert index.search('') == []
        assert index.search('the and of') == []

    def test_results_carry_title(self, index):
        assert index.search('Suno')[0]['title'] == 'Suno'

    def test_unbuilt_index_raises(self):
        with pytest.raises(RuntimeError):
            BM25Index().search('anything')

    def test_roundtrip_save_load(self, index, tmp_path):
        path = str(tmp_path / 'bm25.pkl')
        index.save(path)
        loaded = BM25Index.load(path)
        assert len(loaded) == len(index)
        assert loaded.search('Suno')[0]['doc_id'] == 's1'

    def test_load_missing_file_explains_the_fix(self, tmp_path):
        with pytest.raises(FileNotFoundError, match='build_indexes'):
            BM25Index.load(str(tmp_path / 'nope.pkl'))

    def test_empty_corpus_raises(self):
        mongo = FakeMongo({'startup': [], 'article': [], 'repo': []})
        with pytest.raises(ValueError, match='No documents'):
            BM25Index().build(mongo)
