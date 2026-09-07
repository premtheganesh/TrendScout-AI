"""Document to text conversion shared by all retrieval channels."""

from typing import Dict, List, Any
import ast
import re

_INVISIBLE = re.compile(r'[   ​‌‍﻿]')
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


def document_text(doc: Dict, collection: str) -> str:
    """Indexable text for one document, most identifying fields first."""
    parts: List[str] = []

    if collection == 'startups':
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

    elif collection == 'articles':
        parts.append(_clean(doc.get('title')))
        parts.append(_clean(doc.get('description')))
        author = _clean(doc.get('author'))
        if author:
            parts.append(f"By {author}")
        categories = _coerce_list(doc.get('categories'))
        if categories:
            parts.append(f"Topics: {', '.join(categories)}")

    elif collection == 'github_repos':
        parts.append(_clean(doc.get('full_name')) or _clean(doc.get('name')))
        parts.append(_clean(doc.get('description')))
        language = _clean(doc.get('primary_language'))
        if language:
            parts.append(f"Written in {language}")
        topics = _coerce_list(doc.get('topics'))
        if topics:
            parts.append(f"Topics: {', '.join(topics)}")
        stars = _clean(doc.get('stars'))
        if stars:
            parts.append(f"{stars} GitHub stars")

    else:
        for field in ('name', 'title', 'full_name', 'description', 'summary'):
            parts.append(_clean(doc.get(field)))

    return '. '.join(p for p in parts if p)


def document_title(doc: Dict, collection: str) -> str:
    if collection == 'startups':
        return _clean(doc.get('name')) or 'Untitled startup'
    if collection == 'articles':
        return _clean(doc.get('title')) or 'Untitled article'
    if collection == 'github_repos':
        return (_clean(doc.get('full_name'))
                or _clean(doc.get('name'))
                or 'Untitled repository')
    return (_clean(doc.get('name'))
            or _clean(doc.get('title'))
            or 'Untitled')


def document_url(doc: Dict, collection: str) -> str:
    for field in ('link', 'article_url', 'html_url', 'url', 'homepage'):
        url = _clean(doc.get(field))
        if url.startswith('http'):
            return url
    return ""
