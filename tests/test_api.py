"""
API contract tests. The LLM is stubbed for /chat so they stay deterministic.
"""

import pytest

from conftest import needs_mongo, needs_indexes

pytestmark = [needs_mongo, needs_indexes]


@pytest.fixture(scope='module')
def client():
    from fastapi.testclient import TestClient
    from src.api import main

    with TestClient(main.app) as test_client:
        yield test_client


@pytest.fixture
def stub_llm(client):
    from src.api import main

    class StubLLM:
        model = 'stub'
        def generate_json(self, prompt, system_prompt=None, temperature=0.0):
            return {'search_query': 'AI music', 'type': 'startup',
                    'location': None, 'since_days': None}
        def generate(self, prompt, system_prompt=None, temperature=0.0,
                     max_tokens=2048, reasoning_effort=None):
            return 'Suno makes AI music [1].'

    pipeline = main.rag_pipeline
    original_llm, original_flag = pipeline.llm, pipeline.llm_available
    pipeline.llm, pipeline.llm_available = StubLLM(), True
    yield
    pipeline.llm, pipeline.llm_available = original_llm, original_flag


class TestRoot:
    def test_health(self, client):
        response = client.get('/')
        assert response.status_code == 200
        assert 'endpoints' in response.json()

    def test_chat_is_advertised(self, client):
        assert 'chat' in client.get('/').json()['endpoints']


class TestSearchEndpoint:
    def test_basic_search(self, client):
        response = client.post('/search', json={'query': 'AI music generation',
                                                'top_k': 5})
        assert response.status_code == 200
        results = response.json()
        assert 0 < len(results) <= 5

    def test_response_shape(self, client):
        result = client.post('/search',
                             json={'query': 'AI startup', 'top_k': 1}).json()[0]
        for field in ('doc_id', 'type', 'rrf_score', 'ranks',
                      'title', 'document'):
            assert field in result

    def test_type_filter(self, client):
        results = client.post('/search', json={
            'query': 'framework', 'type': 'repo', 'top_k': 5,
        }).json()
        assert results
        assert all(r['type'] == 'repo' for r in results)

    def test_unknown_type_is_rejected(self, client):
        response = client.post('/search', json={'query': 'x', 'type': 'podcasts'})
        assert response.status_code == 422

    def test_raw_database_filters_are_rejected(self, client):
        """The old API forwarded a client-supplied Mongo query verbatim."""
        response = client.post('/search', json={
            'query': 'x', 'filters': {'$where': 'sleep(1000)'}})
        assert response.status_code == 422

    def test_typed_filters_apply(self, client):
        results = client.post('/search', json={
            'query': 'AI', 'type': 'startup', 'location': 'San Francisco', 'top_k': 5}).json()
        assert results
        assert all('san francisco' in r['document']['location'].lower() for r in results)

    def test_since_days_only_returns_dated_documents(self, client):
        results = client.post('/search', json={
            'query': 'AI', 'since_days': 365, 'top_k': 10}).json()
        assert results
        assert all(r['document'].get('event_at') for r in results)

    def test_top_k_is_capped(self, client):
        assert client.post('/search', json={'query': 'x', 'top_k': 500}).status_code == 422

    def test_channels_can_be_toggled(self, client):
        results = client.post('/search', json={
            'query': 'Suno', 'use_semantic': False, 'use_graph': False,
        }).json()
        assert results
        assert all(set(r['ranks']) == {'keyword'} for r in results)

    def test_empty_query_returns_empty_list(self, client):
        assert client.post('/search', json={'query': ''}).json() == []

    def test_missing_query_is_rejected(self, client):
        assert client.post('/search', json={'top_k': 5}).status_code == 422

    def test_bad_type_is_rejected(self, client):
        response = client.post('/search',
                               json={'query': 'x', 'top_k': 'five'})
        assert response.status_code == 422


class TestSimilarEndpoint:
    def test_returns_hydrated_documents_of_the_same_type(self, client):
        seed = client.post('/search', json={'query': 'Suno', 'top_k': 1}).json()[0]
        results = client.post('/similar', json={'doc_id': seed['doc_id'],
                                                'top_k': 3}).json()
        assert 0 < len(results) <= 3
        assert all(r['doc_id'] != seed['doc_id'] for r in results)
        assert all(r['type'] == seed['type'] for r in results)
        assert all(r['document'] and r['title'] for r in results)

    def test_unknown_document_is_404(self, client):
        response = client.post('/similar', json={'doc_id': '000000000000000000000000'})
        assert response.status_code == 404


class TestChatEndpoint:
    def test_returns_answer_and_sources(self, client, stub_llm):
        response = client.post('/chat', json={
            'question': 'What AI music startups are there?', 'top_k': 5})
        assert response.status_code == 200
        payload = response.json()
        assert payload['answer'] == 'Suno makes AI music [1].'
        assert payload['sources']
        assert payload['search_query'] == 'AI music'

    def test_sources_are_numbered_and_described(self, client, stub_llm):
        sources = client.post('/chat', json={
            'question': 'AI music startups?', 'top_k': 3}).json()['sources']
        assert [s['n'] for s in sources] == list(range(1, len(sources) + 1))
        assert all(s['title'] for s in sources)

    def test_empty_question_is_rejected(self, client, stub_llm):
        assert client.post('/chat', json={'question': '   '}).status_code == 400

    def test_missing_question_is_rejected(self, client):
        assert client.post('/chat', json={'top_k': 5}).status_code == 422

    def test_history_is_accepted(self, client, stub_llm):
        response = client.post('/chat', json={
            'question': 'and who funded them?',
            'history': [{'role': 'user', 'content': 'tell me about Suno'},
                        {'role': 'assistant', 'content': 'Suno makes music.'}],
        })
        assert response.status_code == 200

    def test_planner_can_be_disabled(self, client, stub_llm):
        payload = client.post('/chat', json={
            'question': 'raw question here', 'use_planner': False}).json()
        assert payload['search_query'] == 'raw question here'

    def test_plan_reports_relaxations(self, client, stub_llm):
        plan = client.post('/chat', json={'question': 'anything'}).json()['plan']
        assert 'relaxations' in plan and 'effective_since_days' in plan

    def test_oversized_question_is_rejected(self, client, stub_llm):
        assert client.post('/chat', json={'question': 'x' * 3000}).status_code == 422

    def test_rate_limit(self, client, stub_llm):
        from src.api import main
        original = main.chat_limiter
        main.chat_limiter = main.RateLimiter(per_minute=2)
        try:
            codes = [client.post('/chat', json={'question': 'q', 'use_planner': False}).status_code
                     for _ in range(3)]
            assert codes == [200, 200, 429]
        finally:
            main.chat_limiter = original


class TestDocumentsEndpoint:
    def test_lists_newest_first(self, client):
        payload = client.get('/documents', params={'limit': 5}).json()
        assert payload['count'] == 5 and payload['total'] > 5
        dates = [d['event_at'] for d in payload['items']]
        assert dates == sorted(dates, reverse=True)
        assert all('embedding' not in d and 'entities' not in d for d in payload['items'])

    def test_type_and_window_filters(self, client):
        payload = client.get('/documents', params={'type': ['repo', 'paper'], 'since_days': 90}).json()
        assert payload['items']
        assert {d['type'] for d in payload['items']} <= {'repo', 'paper'}

    def test_unknown_type_is_422(self, client):
        assert client.get('/documents', params={'type': 'podcast'}).status_code == 422

    def test_single_document(self, client):
        first = client.get('/documents', params={'limit': 1}).json()['items'][0]
        doc = client.get(f"/documents/{first['_id']}").json()
        assert doc['_id'] == first['_id'] and 'entities' in doc and 'embedding' not in doc

    def test_missing_or_malformed_id_is_404(self, client):
        assert client.get('/documents/000000000000000000000000').status_code == 404
        assert client.get('/documents/not-an-id').status_code == 404


class TestOperationsEndpoints:
    def test_health(self, client):
        payload = client.get('/health').json()
        assert payload['status'] == 'ok'
        assert payload['documents'] > 0 and payload['vectors'] > 0

    def test_meta_reports_freshness(self, client):
        payload = client.get('/meta').json()
        assert payload['documents']['total'] > 0
        assert payload['index']['dimension'] == 768
        assert 'sources' in payload and 'newest_event_at' in payload

    def test_reload_requires_a_token(self, client, monkeypatch):
        from src.config import get_settings
        monkeypatch.setenv('ADMIN_TOKEN', 'secret-for-test')
        get_settings.cache_clear()
        try:
            assert client.post('/admin/reload').status_code == 401
            assert client.post('/admin/reload',
                               headers={'Authorization': 'Bearer wrong'}).status_code == 401
            response = client.post('/admin/reload',
                                   headers={'Authorization': 'Bearer secret-for-test'})
            assert response.status_code == 200
            assert response.json()['reloaded'] is True
        finally:
            get_settings.cache_clear()

    def test_reload_is_closed_when_no_token_is_configured(self, client, monkeypatch):
        from src.config import get_settings
        monkeypatch.setenv('ADMIN_TOKEN', '')
        get_settings.cache_clear()
        try:
            assert client.post('/admin/reload',
                               headers={'Authorization': 'Bearer '}).status_code == 503
        finally:
            get_settings.cache_clear()


class TestStatsEndpoint:
    def test_reports_corpus_and_index_size(self, client):
        stats = client.get('/stats').json()
        assert stats['documents']['total'] > 0
        assert set(stats['documents']['by_type']) >= {'startup', 'article', 'repo'}
        assert stats['embeddings']['dimension'] == 768

    def test_neo4j_status_is_reported_not_fatal(self, client):
        # Graph endpoints degrade to 503; the rest of the API must stay up.
        assert 'status' in client.get('/stats').json()['neo4j']


class TestGraphEndpointsDegrade:
    @pytest.fixture
    def admin(self, monkeypatch):
        from src.config import get_settings
        monkeypatch.setenv('ADMIN_TOKEN', 'graph-test-token')
        get_settings.cache_clear()
        yield {'Authorization': 'Bearer graph-test-token'}
        get_settings.cache_clear()

    def test_graph_query_requires_the_admin_token(self, client, admin):
        response = client.post('/graph/query', json={'query': 'MATCH (n) RETURN n LIMIT 1'})
        assert response.status_code == 401

    def test_write_cypher_is_rejected_before_neo4j(self, client, admin):
        response = client.post('/graph/query', headers=admin,
                               json={'query': 'MATCH (n) DETACH DELETE n'})
        assert response.status_code == 400

    def test_graph_query_returns_503_when_neo4j_is_down(self, client, admin):
        from src.api import main
        if main.neo4j_client is not None and main.neo4j_client.available:
            pytest.skip('Neo4j is running — degradation path not exercised')
        response = client.post('/graph/query', headers=admin,
                               json={'query': 'MATCH (n) RETURN n LIMIT 1'})
        assert response.status_code == 503
        assert 'neo4j' in response.json()['detail'].lower()
