"""
Document to text conversion shared by all retrieval channels.

This is the single definition of what a document *says*: BM25, the
embedder, the entity extractor, the RAG context builder and the content
hash all read it. If they disagreed, RRF would be fusing rankings over
different texts.
"""

from typing import Dict, List, Any
import ast
import re

from src.corpus.types import normalize_type

_INVISIBLE = re.compile(r'[   ​‌‍﻿]')
_WS = re.compile(r'\s+')


def normalize_whitespace(text: str) -> str:
    return _WS.sub(' ', _INVISIBLE.sub(' ', text)).strip()


def _coerce_list(value: Any) -> List[str]:
    """Some scraped list fields were stored as their Python repr."""
    if isinstance(value, list):
        return [normalize_whitespace(str(v)) for v in value
                if normalize_whitespace(str(v))]

    if isinstance(value, str):
        text = value.strip()
        if text.startswith('[') and text.endswith(']'):
            try:
                parsed = ast.literal_eval(text)
                if isinstance(parsed, (list, tuple)):
                    return [normalize_whitespace(str(v)) for v in parsed
                            if normalize_whitespace(str(v))]
            except (ValueError, SyntaxError):
                pass
        return [text] if text else []

    return []


def _clean(value: Any) -> str:
    if value is None:
        return ""
    text = normalize_whitespace(str(value))
    if text.lower() in ("none", "nan", "n/a", "null", "[]", ""):
        return ""
    return text


def _resolve_type(doc: Dict, doc_type: Any) -> str:
    """Registered type from the argument, else from the document itself,
    else whatever was passed (unknown types get the generic rendering)."""
    return (normalize_type(doc_type)
            or normalize_type(doc.get('type'))
            or (doc_type if isinstance(doc_type, str) else ''))


def document_text(doc: Dict, doc_type: str = None) -> str:
    """Indexable text for one document, most identifying fields first."""
    doc_type = _resolve_type(doc, doc_type)
    parts: List[str] = []

    if doc_type == 'startup':
        parts.append(_clean(doc.get('name')))
        parts.append(_clean(doc.get('description')))
        location = _clean(doc.get('location'))
        if location:
            parts.append(f"Located in {location}")
        funding = _clean(doc.get('funding'))
        if funding:
            parts.append(f"Funding: {funding}")
        investors = _coerce_list(doc.get('investors'))
        if investors:
            parts.append(f"Investors: {', '.join(investors)}")

    elif doc_type == 'article':
        parts.append(_clean(doc.get('title')))
        parts.append(_clean(doc.get('description')))
        author = _clean(doc.get('author'))
        if author:
            parts.append(f"By {author}")
        categories = _coerce_list(doc.get('categories'))
        if categories:
            parts.append(f"Topics: {', '.join(categories)}")

    elif doc_type == 'repo':
        parts.append(_clean(doc.get('full_name')) or _clean(doc.get('name')))
        parts.append(_clean(doc.get('description')))
        language = _clean(doc.get('primary_language'))
        if language:
            parts.append(f"Written in {language}")
        topics = _coerce_list(doc.get('topics'))
        if topics:
            parts.append(f"Topics: {', '.join(topics)}")
        # Star counts are deliberately NOT part of the text: they change
        # weekly, and content_hash over this text decides what gets
        # re-embedded. The number is stored on the document for display.

    elif doc_type == 'launch':
        parts.append(_clean(doc.get('title')))
        parts.append(_clean(doc.get('description')))
        company = _clean(doc.get('company_name'))
        batch = _clean(doc.get('yc_batch'))
        if company and batch:
            parts.append(f"Launched by {company} (YC {batch})")
        elif company:
            parts.append(f"Launched by {company}")
        tags = _coerce_list(doc.get('tags'))
        if tags:
            parts.append(f"Topics: {', '.join(tags)}")
        platform = _clean(doc.get('platform'))
        kind = _clean(doc.get('kind'))
        if platform == 'hn':
            parts.append(f"Posted on Hacker News as {kind or 'Show HN'}")
        elif platform == 'yc':
            parts.append("Posted on Y Combinator Launches")

    elif doc_type == 'model':
        parts.append(_clean(doc.get('hf_id')) or _clean(doc.get('name')))
        organization = _clean(doc.get('organization'))
        if organization:
            parts.append(f"Published by {organization} on Hugging Face")
        task = _clean(doc.get('pipeline_tag'))
        if task:
            parts.append(f"Task: {task.replace('-', ' ')}")
        library = _clean(doc.get('library_name'))
        if library:
            parts.append(f"Library: {library}")
        tags = _coerce_list(doc.get('tags'))
        if tags:
            parts.append(f"Tags: {', '.join(tags[:12])}")

    elif doc_type == 'paper':
        parts.append(_clean(doc.get('title')))
        parts.append(_clean(doc.get('summary')))
        keywords = _coerce_list(doc.get('keywords'))
        if keywords:
            parts.append(f"Keywords: {', '.join(keywords)}")
        authors = _coerce_list(doc.get('authors'))
        if authors:
            parts.append(f"Authors: {', '.join(authors[:5])}")
        organization = _clean(doc.get('organization'))
        if organization:
            parts.append(f"Organization: {organization}")
        repo = _clean(doc.get('github_repo'))
        if repo:
            parts.append(f"Code: {repo}")

    else:
        for field in ('name', 'title', 'full_name', 'description', 'summary'):
            parts.append(_clean(doc.get(field)))

    return '. '.join(p for p in parts if p)


# Shown to the answer model but never indexed: they change weekly and
# would churn content_hash, and they are numbers, not meaning.
_CONTEXT_METRICS = (
    ('event_at', 'Date'), ('stars', 'GitHub stars'), ('forks', 'Forks'),
    ('likes', 'Likes'), ('downloads', 'Downloads'), ('points', 'Points'),
    ('num_comments', 'Comments'), ('upvotes', 'Upvotes'), ('github_stars', 'Code stars'),
    ('funding', 'Funding'), ('yc_batch', 'YC batch'), ('publisher', 'Publisher'),
    ('source', 'Source'),
)


def document_context(doc: Dict, doc_type: str = None, max_chars: int = 900) -> str:
    """The text an answer model should see: the indexed text plus the
    dated, numeric facts the index deliberately leaves out."""
    text = document_text(doc, doc_type)[:max_chars]
    extras = []
    for field, label in _CONTEXT_METRICS:
        value = doc.get(field)
        if value in (None, '', 0, 'Unknown', []):
            continue
        if field == 'event_at':
            value = value.date().isoformat() if hasattr(value, 'date') else str(value)[:10]
        if field == 'funding' and 'Funding:' in text:
            continue
        extras.append(f"{label}: {value}")
    return text + ('\n' + ' · '.join(extras) if extras else '')


def document_title(doc: Dict, doc_type: str = None) -> str:
    doc_type = _resolve_type(doc, doc_type)
    if doc_type == 'startup':
        return _clean(doc.get('name')) or 'Untitled startup'
    if doc_type == 'article':
        return _clean(doc.get('title')) or 'Untitled article'
    if doc_type == 'repo':
        return (_clean(doc.get('full_name'))
                or _clean(doc.get('name'))
                or 'Untitled repository')
    if doc_type == 'launch':
        return _clean(doc.get('title')) or 'Untitled launch'
    if doc_type == 'model':
        return _clean(doc.get('hf_id')) or _clean(doc.get('name')) or 'Untitled model'
    if doc_type == 'paper':
        return _clean(doc.get('title')) or 'Untitled paper'
    return (_clean(doc.get('name'))
            or _clean(doc.get('title'))
            or 'Untitled')


def document_url(doc: Dict, doc_type: str = None) -> str:
    for field in ('link', 'article_url', 'html_url', 'url', 'homepage'):
        url = _clean(doc.get(field))
        if url.startswith('http'):
            return url
    return ""
