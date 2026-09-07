"""Document to text conversion."""

from src.search.document_text import (
    document_text, document_title, document_url, _coerce_list, _clean
)


class TestCoerceList:
    def test_real_list_passes_through(self):
        assert _coerce_list(['a', 'b']) == ['a', 'b']

    def test_repr_string_is_recovered(self):
        assert _coerce_list("['AI', 'Startups']") == ['AI', 'Startups']

    def test_plain_string_becomes_single_item(self):
        assert _coerce_list("AI") == ["AI"]

    def test_empty_values_are_dropped(self):
        assert _coerce_list("['AI', '', 'ML']") == ['AI', 'ML']

    def test_none_is_empty(self):
        assert _coerce_list(None) == []

    def test_malformed_repr_does_not_raise(self):
        assert _coerce_list("['unclosed") == ["['unclosed"]


class TestClean:
    def test_strips_whitespace(self):
        assert _clean('  hello  ') == 'hello'

    def test_null_like_values_become_empty(self):
        for value in (None, 'None', 'n/a', 'NULL', '[]', ''):
            assert _clean(value) == '', f'{value!r} should be empty'


class TestDocumentText:
    def test_startup_includes_all_searchable_fields(self, sample_startup):
        text = document_text(sample_startup, 'startups')
        assert 'Suno' in text
        assert 'AI music generation' in text
        assert 'Cambridge' in text
        assert 'Series B' in text
        assert 'Lightspeed' in text

    def test_repo_includes_language_and_topics(self, sample_repo):
        text = document_text(sample_repo, 'github_repos')
        assert 'langchain-ai/langchain' in text
        assert 'Python' in text
        assert 'agents' in text

    def test_article_includes_author_and_categories(self, sample_article):
        text = document_text(sample_article, 'articles')
        assert 'AI startup raises $50M' in text
        assert 'Julie Bort' in text
        assert 'Startups' in text

    def test_missing_fields_are_skipped_not_rendered_as_none(self):
        text = document_text({'name': 'X'}, 'startups')
        assert text == 'X'
        assert 'None' not in text

    def test_empty_document_yields_empty_string(self):
        assert document_text({}, 'startups') == ''

    def test_unknown_collection_still_extracts_something(self):
        text = document_text({'name': 'Thing', 'description': 'A thing'}, 'mystery')
        assert 'Thing' in text


class TestTitleAndUrl:
    def test_titles_per_collection(self, sample_startup, sample_repo, sample_article):
        assert document_title(sample_startup, 'startups') == 'Suno'
        assert document_title(sample_repo, 'github_repos') == 'langchain-ai/langchain'
        assert document_title(sample_article, 'articles') == 'AI startup raises $50M'

    def test_title_falls_back_when_missing(self):
        assert document_title({}, 'startups') == 'Untitled startup'

    def test_url_picks_the_right_field(self, sample_startup, sample_repo, sample_article):
        assert document_url(sample_startup, 'startups') == 'https://suno.com'
        assert document_url(sample_repo, 'github_repos').endswith('langchain')
        assert 'techcrunch' in document_url(sample_article, 'articles')

    def test_url_empty_when_absent(self):
        assert document_url({}, 'startups') == ''

    def test_non_http_values_are_rejected(self):
        assert document_url({'link': 'not-a-url'}, 'startups') == ''
