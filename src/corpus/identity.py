"""
Stable identity for documents.

`doc_key` is what makes ingestion idempotent: re-fetching the same startup,
article or repository produces the same key, so the store updates the
existing record instead of inserting a duplicate. `content_hash` says
whether the indexed text changed, which decides what gets re-embedded.
"""

import hashlib
import re
from typing import Dict, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from src.search.document_text import document_text

_TRACKING_PARAMS = {'fbclid', 'gclid', 'ref', 'ref_src', 'mc_cid', 'mc_eid', 'igshid'}
_LEGAL_SUFFIX = re.compile(r'\b(inc|llc|ltd|corp|co|gmbh|plc)\b\.?', re.IGNORECASE)
_NON_ALNUM = re.compile(r'[^a-z0-9]+')
_YC_SLUG = re.compile(r'/companies/([^/?#]+)')


def canonical_url(url: str) -> str:
    """https, lowercase host without www., no fragment, no tracking
    parameters, no trailing slash. Empty string for anything unusable."""
    if not url or not isinstance(url, str):
        return ''
    url = url.strip()
    if not url.lower().startswith(('http://', 'https://')):
        return ''
    parts = urlsplit(url)
    host = parts.netloc.lower()
    if host.startswith('www.'):
        host = host[4:]
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False)
             if not k.lower().startswith('utm_') and k.lower() not in _TRACKING_PARAMS]
    path = parts.path.rstrip('/') or ''
    return urlunsplit(('https', host, path, urlencode(query), ''))


def name_key(name: str) -> str:
    """Casefolded, alphanumeric-only company name with legal suffixes
    removed. "AI" is deliberately kept: "Harvey AI" and "Harvey" are not
    the same company."""
    if not name or not isinstance(name, str):
        return ''
    text = _LEGAL_SUFFIX.sub(' ', name.casefold())
    return _NON_ALNUM.sub('', text)


def doc_key(doc: Dict, doc_type: str) -> str:
    """The unique key for a document of the given type."""
    if doc_type == 'startup':
        source = (doc.get('source') or 'manual').lower()
        if source == 'ycombinator':
            match = _YC_SLUG.search(doc.get('company_url') or doc.get('url') or '')
            if match:
                return f'startup:yc:{match.group(1).lower()}'
            source = 'yc'
        elif source == 'startupsavant':
            source = 'savant'
        key = name_key(doc.get('name'))
        if not key:
            raise ValueError('startup has no name to key on')
        return f'startup:{source}:{key}'

    if doc_type == 'article':
        url = canonical_url(doc.get('article_url') or doc.get('url') or doc.get('link') or '')
        if url:
            return f'article:{url}'
        key = name_key(doc.get('title'))
        if not key:
            raise ValueError('article has neither URL nor title to key on')
        return f'article:{(doc.get("source") or "unknown").lower()}:{key}'

    if doc_type == 'repo':
        full_name = (doc.get('full_name') or '').strip().lower()
        if not full_name:
            raise ValueError('repo has no full_name to key on')
        return f'repo:gh:{full_name}'

    raise ValueError(f'no doc_key rule for type {doc_type!r}')


def content_hash(doc: Dict, doc_type: Optional[str] = None) -> str:
    """sha1 of exactly the text that gets indexed, so "changed" means
    "would embed differently"."""
    text = document_text(doc, doc_type)
    return hashlib.sha1(text.encode('utf-8')).hexdigest()
