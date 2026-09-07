"""
RAG pipeline plumbing: plan validation, context construction, citation
numbering and graceful degradation. The LLM is stubbed throughout.
"""

import pytest

from src.rag.pipeline import RAGPipeline, normalize_citations, Source


class StubSearch:
    def __init__(self, results=None):
        self.results = results if results is not None else []
        self.calls = []

    def search(self, query, collection=None, filters=None, top_k=10, **kwargs):
        self.calls.append({'query': query, 'collection': collection,
                           'filters': filters, 'top_k': top_k})
        return self.results


class StubLLM:
    model = 'stub-model'

    def __init__(self, json_response=None, text_response="An answer [1].",
                 fail_json=False, fail_text=False):
        self.json_response = json_response or {}
        self.text_response = text_response
        self.fail_json = fail_json
        self.fail_text = fail_text
        self.prompts = []

    def generate_json(self, prompt, system_prompt=None, temperature=0.0):
        if self.fail_json:
            raise RuntimeError("planner exploded")
        return self.json_response

    def generate(self, prompt, system_prompt=None, temperature=0.0,
                 max_tokens=2048, reasoning_effort=None):
        self.prompts.append(prompt)
        if self.fail_text:
            raise RuntimeError("generation exploded")
        return self.text_response


def result(doc_id='d1', collection='startups', name='Suno', **extra):
    return {
        'doc_id': doc_id,
        'collection': collection,
        'rrf_score': 0.032,
        'ranks': {'keyword': 1},
        'document': {'_id': doc_id, 'name': name,
                     'description': 'AI music generation',
                     'location': 'Cambridge', 'link': 'https://suno.com'},
        'title': name,
        'url': 'https://suno.com',
        **extra,
    }


def make_pipeline(search=None, llm=None):
    pipeline = RAGPipeline.__new__(RAGPipeline)
    pipeline.search = search or StubSearch()
    pipeline.context_size = 8
    pipeline.llm = llm
    pipeline.llm_available = llm is not None
    return pipeline


class TestNormalizeCitations:
    def test_converts_cjk_brackets(self):
        assert normalize_citations('Suno【1】') == 'Suno[1]'

    def test_handles_inner_spaces(self):
        assert normalize_citations('x【 2 】') == 'x[2]'

    def test_leaves_ascii_untouched(self):
        assert normalize_citations('already [3]') == 'already [3]'

    def test_multiple_citations(self):
        assert normalize_citations('a【1】b【22】') == 'a[1]b[22]'


class TestPlanQuery:
    def test_uses_the_models_plan(self):
        llm = StubLLM(json_response={'search_query': 'AI music',
                                     'collection': 'startups',
                                     'location': 'Boston'})
        plan = make_pipeline(llm=llm).plan_query('where is AI music in Boston?')
        assert plan == {'search_query': 'AI music',
                        'collection': 'startups', 'location': 'Boston'}

    def test_rejects_an_invalid_collection(self):
        llm = StubLLM(json_response={'search_query': 'x',
                                     'collection': 'not_a_collection',
                                     'location': None})
        assert make_pipeline(llm=llm).plan_query('q')['collection'] is None

    def test_falls_back_when_planner_raises(self):
        pipeline = make_pipeline(llm=StubLLM(fail_json=True))
        assert pipeline.plan_query('my question')['search_query'] == 'my question'

    def test_falls_back_on_empty_query(self):
        llm = StubLLM(json_response={'search_query': '   '})
        assert make_pipeline(llm=llm).plan_query('original')['search_query'] == 'original'

    def test_non_string_location_is_dropped(self):
        llm = StubLLM(json_response={'search_query': 'x', 'location': 42})
        assert make_pipeline(llm=llm).plan_query('q')['location'] is None

    def test_without_an_llm_the_question_is_used_verbatim(self):
        plan = make_pipeline(llm=None).plan_query('raw question')
        assert plan['search_query'] == 'raw question'
        assert plan['collection'] is None


class TestRetrieve:
    def test_location_becomes_a_regex_filter(self):
        search = StubSearch(results=[result()])
        make_pipeline(search=search).retrieve(
            {'search_query': 'q', 'collection': None, 'location': 'Boston'}, 5)
        assert search.calls[0]['filters'] == {
            'location': {'$regex': 'Boston', '$options': 'i'}}

    def test_no_filter_when_no_location(self):
        search = StubSearch(results=[result()])
        make_pipeline(search=search).retrieve(
            {'search_query': 'q', 'collection': None, 'location': None}, 5)
        assert search.calls[0]['filters'] is None

    def test_empty_filtered_result_retries_unfiltered(self):
        search = StubSearch(results=[])
        make_pipeline(search=search).retrieve(
            {'search_query': 'q', 'collection': None, 'location': 'Atlantis'}, 5)
        assert len(search.calls) == 2
        assert search.calls[1]['filters'] is None


class TestBuildContext:
    def test_sources_are_numbered_from_one(self):
        _, sources = make_pipeline().build_context(
            [result('a'), result('b'), result('c')])
        assert [s.n for s in sources] == [1, 2, 3]

    def test_context_labels_each_source(self):
        context, _ = make_pipeline().build_context([result()])
        assert context.startswith('[1] Startup: Suno')

    def test_context_includes_the_url(self):
        context, _ = make_pipeline().build_context([result()])
        assert 'https://suno.com' in context

    def test_long_documents_are_truncated(self):
        long_doc = result()
        long_doc['document']['description'] = 'x' * 5000
        context, sources = make_pipeline().build_context([long_doc])
        assert len(context) < 2000
        assert len(sources[0].snippet) <= 280

    def test_empty_results_give_empty_context(self):
        context, sources = make_pipeline().build_context([])
        assert context == ''
        assert sources == []

    def test_source_carries_provenance(self):
        _, sources = make_pipeline().build_context(
            [result(shared_entities=['OpenAI'])])
        assert sources[0].ranks == {'keyword': 1}
        assert sources[0].shared_entities == ['OpenAI']


class TestGenerate:
    def test_prompt_contains_the_sources(self):
        llm = StubLLM()
        make_pipeline(llm=llm).generate('q', 'CONTEXT_MARKER')
        assert 'CONTEXT_MARKER' in llm.prompts[0]

    def test_history_is_included(self):
        llm = StubLLM()
        make_pipeline(llm=llm).generate(
            'follow up', 'ctx',
            history=[{'role': 'user', 'content': 'EARLIER_TURN'}])
        assert 'EARLIER_TURN' in llm.prompts[0]

    def test_empty_context_short_circuits_without_calling_the_model(self):
        llm = StubLLM()
        answer = make_pipeline(llm=llm).generate('q', '')
        assert 'Nothing in the indexed corpus' in answer
        assert llm.prompts == []

    def test_missing_llm_is_reported_not_crashed(self):
        answer = make_pipeline(llm=None).generate('q', 'ctx')
        assert 'GROQ_API_KEY' in answer

    def test_generation_failure_is_reported_not_raised(self):
        answer = make_pipeline(llm=StubLLM(fail_text=True)).generate('q', 'ctx')
        assert 'failed' in answer.lower()

    def test_citations_are_normalized(self):
        llm = StubLLM(text_response='Suno【1】 is a startup.')
        assert make_pipeline(llm=llm).generate('q', 'ctx') == 'Suno[1] is a startup.'


class TestAnswer:
    def test_end_to_end_shape(self):
        search = StubSearch(results=[result()])
        llm = StubLLM(json_response={'search_query': 'AI music',
                                     'collection': 'startups'},
                      text_response='Suno makes AI music [1].')
        answer = make_pipeline(search=search, llm=llm).answer('q')

        assert answer.answer == 'Suno makes AI music [1].'
        assert len(answer.sources) == 1
        assert answer.search_query == 'AI music'
        assert answer.used_llm_planner is True

    def test_planner_can_be_disabled_for_reproducibility(self):
        search = StubSearch(results=[result()])
        llm = StubLLM(json_response={'search_query': 'REWRITTEN'})
        answer = make_pipeline(search=search, llm=llm).answer(
            'original question', use_planner=False)
        assert search.calls[0]['query'] == 'original question'
        assert answer.used_llm_planner is False

    def test_to_dict_is_serializable(self):
        import json
        search = StubSearch(results=[result()])
        llm = StubLLM(json_response={'search_query': 'x'})
        payload = make_pipeline(search=search, llm=llm).answer('q').to_dict()
        json.dumps(payload)   # must not raise
        assert payload['sources'][0]['title'] == 'Suno'

    def test_retrieval_still_works_without_an_llm(self):
        search = StubSearch(results=[result()])
        answer = make_pipeline(search=search, llm=None).answer('q')
        assert len(answer.sources) == 1
        assert answer.used_llm_planner is False
