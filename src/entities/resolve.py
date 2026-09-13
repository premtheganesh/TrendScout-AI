"""
Resolve documents to companies, strictly and measurably.

Match order, first hit wins, no fuzzy matching anywhere:
    1. YC slug          (startup.yc_slug, launch.company_slug)
    2. registered domain (website / company link)
    3. normalised name   (name_key) — and only when exactly one company has it

Companies are recomputed from scratch on every run, so the collection is
a deterministic function of `documents` and `funding_rounds`, never a
store of accumulated guesses.
"""

import logging
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

from src.corpus.identity import name_key
from src.corpus.types import COLLECTION

logger = logging.getLogger(__name__)

COMPANIES = 'companies'
FUNDING_ROUNDS = 'funding_rounds'

# Hosts that never identify a company.
_SHARED_HOSTS = {
    'ycombinator.com', 'github.com', 'gitlab.com', 'linkedin.com', 'twitter.com', 'x.com',
    'medium.com', 'substack.com', 'notion.site', 'notion.so', 'google.com', 'docs.google.com',
    'apps.apple.com', 'play.google.com', 'producthunt.com', 'huggingface.co', 'youtube.com',
    'youtu.be', 'discord.gg', 'discord.com', 'apple.com', 'vercel.app', 'netlify.app',
    'webflow.io', 'framer.website', 'framer.ai', 'carrd.co', 'gumroad.com', 'typeform.com',
}
_PUBLIC_SUFFIX_2 = {'co.uk', 'com.au', 'co.jp', 'com.br', 'co.in', 'co.nz', 'com.sg', 'org.uk', 'ac.uk'}


def registered_domain(url: Optional[str]) -> str:
    """'https://www.app.withspecific.com/x' -> 'withspecific.com'. Empty for
    shared hosts and unusable input."""
    if not url or not isinstance(url, str) or not url.lower().startswith(('http://', 'https://')):
        return ''
    host = urlsplit(url).netloc.lower().split(':')[0]
    if host.startswith('www.'):
        host = host[4:]
    parts = host.split('.')
    if len(parts) < 2:
        return ''
    if len(parts) >= 3 and '.'.join(parts[-2:]) in _PUBLIC_SUFFIX_2:
        domain = '.'.join(parts[-3:])
    else:
        domain = '.'.join(parts[-2:])
    return '' if domain in _SHARED_HOSTS else domain


def company_slug(yc_slug: str, domain: str, key: str) -> str:
    if yc_slug:
        return f'yc-{yc_slug}'
    if domain:
        return 'd-' + re.sub(r'[^a-z0-9]+', '-', domain)
    return f'n-{key}'


class Resolver:
    """Index of known companies by each identity, built from startups first."""

    def __init__(self):
        self.companies: Dict[str, Dict[str, Any]] = {}
        self.by_yc: Dict[str, str] = {}
        self.by_domain: Dict[str, str] = {}
        self.by_key: Dict[str, List[str]] = defaultdict(list)

    # -- building -----------------------------------------------------
    def _register(self, slug: str, company: Dict[str, Any]) -> None:
        self.companies[slug] = company
        if company.get('yc_slug'):
            self.by_yc[company['yc_slug']] = slug
        if company.get('domain'):
            self.by_domain[company['domain']] = slug
        if company.get('name_key') and slug not in self.by_key[company['name_key']]:
            self.by_key[company['name_key']].append(slug)

    def add_startup(self, doc: Dict[str, Any]) -> str:
        name = (doc.get('name') or '').strip()
        key = name_key(name)
        yc_slug = (doc.get('yc_slug') or '').lower()
        domain = registered_domain(doc.get('link') or doc.get('website'))
        # Two startup records merge only on a strong identity. Merging on
        # the name alone would fold two different "Candor"s into one.
        existing = self.match(yc_slug=yc_slug, domain=domain)
        if existing:
            company = self.companies[existing]
            # Enrich, never overwrite a stronger identity.
            for field, value in (('yc_slug', yc_slug), ('domain', domain)):
                if value and not company.get(field):
                    company[field] = value
            company.setdefault('doc_ids', {}).setdefault('startup', []).append(str(doc['_id']))
            self._register(existing, company)
            return existing

        slug = company_slug(yc_slug, domain, key or str(doc['_id']))
        company = {
            '_id': slug,
            'name': name,
            'name_key': key,
            'yc_slug': yc_slug,
            'domain': domain,
            'website': doc.get('link') or '',
            'yc_batch': doc.get('yc_batch') or '',
            'location': doc.get('location') or '',
            'description': doc.get('one_liner') or doc.get('description') or '',
            'tags': list(doc.get('tags') or []),
            'launched_at': doc.get('event_at'),
            'doc_ids': {'startup': [str(doc['_id'])]},
        }
        self._register(slug, company)
        return slug

    # -- matching -----------------------------------------------------
    def match(self, yc_slug: str = '', domain: str = '', key: str = '') -> Optional[str]:
        if yc_slug and yc_slug in self.by_yc:
            return self.by_yc[yc_slug]
        if domain and domain in self.by_domain:
            return self.by_domain[domain]
        if key and len(self.by_key.get(key, [])) == 1:
            return self.by_key[key][0]
        return None

    def attach(self, slug: str, doc_type: str, doc_id: str) -> None:
        ids = self.companies[slug].setdefault('doc_ids', {}).setdefault(doc_type, [])
        if doc_id not in ids:
            ids.append(doc_id)


def build_companies(db) -> Dict[str, int]:
    """Recompute `companies` from documents and funding rounds."""
    resolver = Resolver()
    docs = db[COLLECTION]
    stats = Counter()

    for doc in docs.find({'type': 'startup'}, {'embedding': 0, 'entities': 0}).sort('_id', 1):
        resolver.add_startup(doc)
        stats['startups'] += 1

    for doc in docs.find({'type': 'launch'}, {'embedding': 0, 'entities': 0}).sort('_id', 1):
        slug = resolver.match(
            yc_slug=(doc.get('company_slug') or '').lower(),
            domain=registered_domain(doc.get('link')),
            key=name_key(doc.get('company_name') or ''),
        )
        if slug:
            resolver.attach(slug, 'launch', str(doc['_id']))
            stats['launches_linked'] += 1
        else:
            stats['launches_unlinked'] += 1

    for round_ in db[FUNDING_ROUNDS].find({'confidence': {'$in': ['high', 'medium']}}).sort('_id', 1):
        key = round_.get('company_key') or ''
        if not key:
            stats['rounds_unlinked'] += 1
            continue
        slug = resolver.match(key=key)
        if slug:
            stats['rounds_linked'] += 1
        else:
            # A company we only know from funding news. A name-only record
            # keeps the round visible on /companies and lets later startup
            # records with the same unambiguous name attach to it.
            slug = f'n-{key}'
            if slug not in resolver.companies:
                resolver._register(slug, {
                    '_id': slug, 'name': round_.get('company') or key, 'name_key': key,
                    'yc_slug': '', 'domain': '', 'website': '', 'yc_batch': '', 'location': '',
                    'description': '', 'tags': [], 'launched_at': None, 'doc_ids': {},
                    'from_news_only': True,
                })
                stats['companies_from_news'] += 1
            stats['rounds_to_news_companies'] += 1
        company = resolver.companies[slug]
        company.setdefault('rounds', []).append(round_['_id'])
        if round_.get('amount_usd'):
            company['funding_total_usd'] = company.get('funding_total_usd', 0) + round_['amount_usd']
        for doc_id in round_.get('source_doc_ids', []):
            resolver.attach(slug, 'article', doc_id)

    now = datetime.now(timezone.utc)
    records = []
    for company in resolver.companies.values():
        company['document_count'] = sum(len(v) for v in company.get('doc_ids', {}).values())
        company['rounds'] = company.get('rounds', [])
        company['funding_total_usd'] = company.get('funding_total_usd', 0)
        company['updated_at'] = now
        records.append(company)

    tmp = COMPANIES + '_building'
    db[tmp].drop()
    if records:
        db[tmp].insert_many(records)
    db[tmp].rename(COMPANIES, dropTarget=True)
    db[COMPANIES].create_index('name_key')
    db[COMPANIES].create_index('domain')
    db[COMPANIES].create_index([('funding_total_usd', -1)])
    stats['companies'] = len(records)
    return dict(stats)
