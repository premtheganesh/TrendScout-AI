"""
RAG pipeline plumbing: plan validation, context construction, citation
numbering and graceful degradation. The LLM is stubbed throughout.
"""

from datetime import datetime, timedelta, timezone

import pytest

from src.rag.pipeline import RAGPipeline, normalize_citations, Source, clamp_since_days


class StubSearch:
    def __init__(self, results=None, responder=None):
        self.results = results if results is not None else []
        self.responder = responder      # optional: filters -> results
        self.calls = []

    def search(self, query, doc_type=None, filters=None, top_k=10, **kwargs):
        self.calls.append({'query': query, 'type': doc_type,
                           'filters': filters, 'top_k': top_k})
        if self.responder is not None:
            return self.responder(filters)
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


def result(doc_id='d1', doc_type='startup', name='Suno', **extra):
    return {
        'doc_id': doc_id,
        'type': doc_type,
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
                                     'type': 'startup',
                                     'location': 'Boston',
                                     'since_days': 30})
        plan = make_pipeline(llm=llm).plan_query('where is AI music in Boston?')
        assert plan == {'search_query': 'AI music', 'type': 'startup',
                        'location': 'Boston', 'since_days': 30}

    def test_since_days_is_clamped_and_validated(self):
        assert clamp_since_days(7) == 7
        assert clamp_since_days('30') == 30
        assert clamp_since_days(10_000) == 365
        assert clamp_since_days(0) is None
        assert clamp_since_days(-5) is None
        assert clamp_since_days(True) is None
        assert clamp_since_days('soon') is None

    def test_planner_prompt_carries_todays_date(self):
        llm = StubLLM(json_response={'search_query': 'x'})
        pipeline = make_pipeline(llm=llm)
        pipeline.plan_query('what launched this week?')
        # generate_json is stubbed; check the prompt through a spy instead
        captured = {}
        def spy(prompt, system_prompt=None, temperature=0.0):
            captured['prompt'] = prompt
            return {'search_query': 'x'}
        llm.generate_json = spy
        pipeline.plan_query('what launched this week?')
        assert f"Today is {pipeline.today().isoformat()}" in captured['prompt']

    def test_rejects_an_invalid_type(self):
        llm = StubLLM(json_response={'search_query': 'x',
                                     'type': 'not_a_type',
                                     'location': None})
        assert make_pipeline(llm=llm).plan_query('q')['type'] is None

    def test_legacy_collection_name_from_the_model_is_mapped(self):
        llm = StubLLM(json_response={'search_query': 'x',
                                     'collection': 'github_repos'})
        assert make_pipeline(llm=llm).plan_query('q')['type'] == 'repo'

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
        assert plan['type'] is None


class TestRetrieve:
    def test_location_becomes_a_regex_filter(self):
        search = StubSearch(results=[result()])
        make_pipeline(search=search).retrieve(
            {'search_query': 'q', 'type': None, 'location': 'Boston'}, 5)
        assert search.calls[0]['filters'] == {
            'location': {'$regex': 'Boston', '$options': 'i'}}

    def test_no_filter_when_no_location(self):
        search = StubSearch(results=[result()])
        make_pipeline(search=search).retrieve(
            {'search_query': 'q', 'type': None, 'location': None}, 5)
        assert search.calls[0]['filters'] is None

    def test_since_days_becomes_an_event_at_window(self):
        search = StubSearch(results=[result()])
        plan = {'search_query': 'q', 'type': None, 'location': None, 'since_days': 7}
        make_pipeline(search=search).retrieve(plan, 5)
        cutoff = search.calls[0]['filters']['event_at']['$gte']
        assert timedelta(days=6, hours=23) < datetime.now(timezone.utc) - cutoff < timedelta(days=7, minutes=1)
        assert plan['relaxations'] == [] and plan['effective_since_days'] == 7

    def test_empty_filtered_result_relaxes_location_first(self):
        search = StubSearch(results=[])
        plan = {'search_query': 'q', 'type': None, 'location': 'Atlantis'}
        make_pipeline(search=search).retrieve(plan, 5)
        assert len(search.calls) == 2
        assert search.calls[1]['filters'] is None
        assert plan['relaxations'] == ['dropped_location']

    def test_date_filter_is_not_dropped_on_retry(self):
        """Dropping the location must keep the date; the window widens
        before the date is ever dropped, and every step is recorded."""
        def responder(filters):
            # Only an undated search returns anything.
            return [result()] if not filters or 'event_at' not in filters else []
        search = StubSearch(responder=responder)
        plan = {'search_query': 'q', 'type': None, 'location': 'Atlantis', 'since_days': 7}
        results = make_pipeline(search=search).retrieve(plan, 5)

        assert results
        steps = [c['filters'] for c in search.calls]
        assert 'location' in steps[0] and 'event_at' in steps[0]
        assert 'location' not in steps[1] and 'event_at' in steps[1]      # date kept
        assert 'event_at' in steps[2]                                      # widened, still dated
        assert steps[3] is None                                            # only now dropped
        assert plan['relaxations'] == ['dropped_location', 'widened_window_to_28_days', 'dropped_date']
        assert plan['effective_since_days'] is None

    def test_widened_window_is_used_when_it_matches(self):
        def responder(filters):
            if filters and 'event_at' in filters:
                age = datetime.now(timezone.utc) - filters['event_at']['$gte']
                return [result()] if age > timedelta(days=20) else []
            return [result()]
        search = StubSearch(responder=responder)
        plan = {'search_query': 'q', 'type': None, 'location': None, 'since_days': 7}
        make_pipeline(search=search).retrieve(plan, 5)
        assert plan['relaxations'] == ['widened_window_to_28_days']
        assert plan['effective_since_days'] == 28

    def test_retrieval_note_explains_the_window(self):
        pipeline = make_pipeline()
        note = pipeline.retrieval_note({'since_days': 7, 'effective_since_days': 28,
                                        'relaxations': ['widened_window_to_28_days']})
        assert 'last 7 days' in note and 'last 28 days' in note
        note = pipeline.retrieval_note({'since_days': 7, 'effective_since_days': None,
                                        'relaxations': ['dropped_date']})
        assert 'not covered' in note


class TestBuildContext:
    def test_sources_are_numbered_from_one(self):
        _, sources = make_pipeline().build_context(
            [result('a'), result('b'), result('c')])
        assert [s.n for s in sources] == [1, 2, 3]

    def test_context_labels_each_source(self):
        context, _ = make_pipeline().build_context([result()])
        assert context.startswith('[1] Startup: Suno')

    def test_context_carries_dates_and_metrics_the_index_leaves_out(self):
        hit = result()
        hit['document'].update({'event_at': datetime(2026, 9, 10, tzinfo=timezone.utc),
                                'funding': 'Series B, $125M', 'source': 'ycombinator'})
        context, _ = make_pipeline().build_context([hit])
        assert 'Date: 2026-09-10' in context and 'Series B' in context

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

    def test_prompt_carries_the_retrieval_note(self):
        llm = StubLLM()
        make_pipeline(llm=llm).generate('q', 'ctx', plan={
            'since_days': 7, 'effective_since_days': 28,
            'relaxations': ['widened_window_to_28_days']})
        assert 'Retrieval note:' in llm.prompts[0] and 'last 28 days' in llm.prompts[0]

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
                                     'type': 'startup'},
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
