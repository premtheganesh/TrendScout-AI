"""
Funding rounds from news articles.

    prefilter (regex on the title)  ->  one Groq JSON call  ->  schema
    validation  ->  rule-derived confidence  ->  dedupe across outlets

Confidence is never the model's opinion of itself. It is 'high' only when
the company name and the amount both appear verbatim in the article text
the model was given; 'medium' when the company does but the amount is
absent or paraphrased; 'low' otherwise.

Each article is processed once per (content_hash, extraction version):
the result — a round id, or "no round here" — is recorded on the article.
"""

import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field, ValidationError, field_validator

from src.corpus.dates import parse_datetime
from src.corpus.identity import name_key
from src.corpus.types import COLLECTION
from src.digest.select import FUNDING_TITLE
from src.search.document_text import normalize_whitespace

logger = logging.getLogger(__name__)

FUNDING_ROUNDS = 'funding_rounds'
EXTRACTION_VERSION = 'funding-v1'

# Approximate, for ranking only; the original amount and currency are kept.
USD_PER = {
    'USD': 1.0, 'EUR': 1.08, 'GBP': 1.27, 'CAD': 0.73, 'AUD': 0.66, 'CHF': 1.12,
    'INR': 0.012, 'JPY': 0.0067, 'SGD': 0.74, 'SEK': 0.095, 'DKK': 0.145, 'NOK': 0.093,
    'ILS': 0.27, 'BRL': 0.18, 'KRW': 0.00073, 'CNY': 0.14, 'AED': 0.27,
}

ROUND_NAMES = ('pre-seed', 'seed', 'series a', 'series b', 'series c', 'series d',
               'series e', 'series f', 'growth', 'bridge', 'angel', 'debt', 'grant', 'other')

SYSTEM_PROMPT = """You extract funding announcements from news articles. \
Respond with JSON only, no prose, no markdown."""

PROMPT = """Article title: {title}
Article text: {text}

Does this article announce that a specific company raised money (a funding
round, investment, or financing)? A valuation without a new round, a fund
raising its own capital, an acquisition, or general market news is NOT a
funding round.

Return JSON with exactly these keys:
{{
  "is_funding_round": true or false,
  "company": string or null      - the company that raised, as written in the article,
  "amount": number or null       - the amount raised, in the currency below (e.g. 75000000 for "$75 million"; 470000000 for "Rs 47 crore"),
  "currency": string or null     - ISO code: USD, EUR, GBP, INR, ...
  "round": string or null        - one of: {rounds}
  "lead_investors": [strings]    - investors named as leading the round,
  "investors": [strings]         - every investor named,
  "announced_on": "YYYY-MM-DD" or null - only if the article states a date,
  "valuation": number or null    - post-money valuation in the same currency, if stated
}}
Use null for anything the article does not state. Never guess an amount."""


class ExtractedRound(BaseModel):
    is_funding_round: bool
    company: Optional[str] = None
    amount: Optional[float] = Field(default=None, ge=0)
    currency: Optional[str] = None
    round: Optional[str] = None
    lead_investors: List[str] = Field(default_factory=list)
    investors: List[str] = Field(default_factory=list)
    announced_on: Optional[str] = None
    valuation: Optional[float] = Field(default=None, ge=0)

    @field_validator('currency')
    @classmethod
    def _upper(cls, value):
        return value.strip().upper()[:3] if isinstance(value, str) and value.strip() else None

    @field_validator('round')
    @classmethod
    def _round(cls, value):
        if not isinstance(value, str) or not value.strip():
            return None
        v = re.sub(r'\s+', ' ', value.strip().lower().replace('_', ' '))
        v = re.sub(r'^series[\s-]*([a-f])$', r'series \1', v)
        v = v.replace('preseed', 'pre-seed').replace('pre seed', 'pre-seed')
        return v if v in ROUND_NAMES else 'other'

    @field_validator('lead_investors', 'investors', mode='before')
    @classmethod
    def _names(cls, value):
        if not isinstance(value, list):
            return []
        return [normalize_whitespace(str(v)) for v in value if str(v).strip()][:12]


def amount_usd(amount: Optional[float], currency: Optional[str]) -> Optional[float]:
    if amount is None or not currency or currency not in USD_PER:
        return None
    return round(amount * USD_PER[currency])


def _amount_strings(amount: float) -> List[str]:
    """Ways an amount may appear in text: 75000000 -> '75 million', '75m', '75,000,000'."""
    forms = [f'{amount:,.0f}']
    for unit, word in ((1e9, 'billion'), (1e6, 'million'), (1e3, 'thousand')):
        if amount >= unit:
            n = amount / unit
            text = f'{n:.2f}'.rstrip('0').rstrip('.')
            forms += [f'{text} {word}', f'{text}{word[0]}', f'{text} {word[0]}']
            if word == 'billion':
                forms += [f'{text}bn']
            break
    return [f.lower() for f in forms]


def confidence_for(extracted: ExtractedRound, text: str) -> str:
    lowered = text.lower()
    company_seen = bool(extracted.company) and extracted.company.lower() in lowered
    if not company_seen:
        return 'low'
    if extracted.amount is None:
        return 'medium'
    amount_seen = any(form in lowered for form in _amount_strings(extracted.amount))
    return 'high' if amount_seen else 'medium'


def round_id(company_key: str, round_name: Optional[str], announced_at: Optional[datetime]) -> str:
    stamp = announced_at.strftime('%Y-%m') if announced_at else 'undated'
    return hashlib.sha1(f'{company_key}|{round_name or ""}|{stamp}'.encode()).hexdigest()[:16]


def to_record(extracted: ExtractedRound, article: Dict[str, Any], text: str,
              model_name: str) -> Dict[str, Any]:
    announced_at = parse_datetime(extracted.announced_on) or article.get('event_at')
    company_key = name_key(extracted.company or '')
    return {
        'company': normalize_whitespace(extracted.company or ''),
        'company_key': company_key,
        'amount': extracted.amount,
        'currency': extracted.currency,
        'amount_usd': amount_usd(extracted.amount, extracted.currency),
        'round': extracted.round,
        'lead_investors': extracted.lead_investors,
        'investors': extracted.investors,
        'valuation': extracted.valuation,
        'announced_at': announced_at,
        'confidence': confidence_for(extracted, text),
        'source_doc_ids': [str(article['_id'])],
        'publishers': [article.get('publisher') or article.get('source') or ''],
        'model': model_name,
        'extraction_version': EXTRACTION_VERSION,
        'extracted_at': datetime.now(timezone.utc),
    }


def same_round(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """Two outlets covering one round: same company, same round name (or
    one unknown), amounts within 10%, dates within 14 days."""
    if a['company_key'] != b['company_key'] or not a['company_key']:
        return False
    if a.get('round') and b.get('round') and a['round'] != b['round']:
        return False
    x, y = a.get('amount_usd'), b.get('amount_usd')
    if x and y and abs(x - y) > 0.1 * max(x, y):
        return False
    da, db_ = a.get('announced_at'), b.get('announced_at')
    if da and db_ and abs(da - db_) > timedelta(days=14):
        return False
    return True


def merge_into(db, record: Dict[str, Any]) -> Tuple[str, str]:
    """Upsert the round, merging with an existing one from another outlet.
    Returns (round id, 'new' | 'merged')."""
    rounds = db[FUNDING_ROUNDS]
    candidates = rounds.find({'company_key': record['company_key']})
    for existing in candidates:
        if same_round(existing, record):
            update = {
                'source_doc_ids': sorted(set(existing.get('source_doc_ids', [])) | set(record['source_doc_ids'])),
                'publishers': sorted(set(existing.get('publishers', [])) | set(record['publishers'])),
                'investors': sorted(set(existing.get('investors', [])) | set(record['investors'])),
                'lead_investors': sorted(set(existing.get('lead_investors', [])) | set(record['lead_investors'])),
            }
            # Prefer the more confident, more complete version of the facts.
            rank = {'high': 3, 'medium': 2, 'low': 1}
            if rank[record['confidence']] > rank.get(existing.get('confidence'), 0):
                for field in ('amount', 'currency', 'amount_usd', 'round', 'valuation', 'confidence', 'company'):
                    if record.get(field) is not None:
                        update[field] = record[field]
            else:
                for field in ('amount', 'currency', 'amount_usd', 'round', 'valuation'):
                    if existing.get(field) is None and record.get(field) is not None:
                        update[field] = record[field]
            if not existing.get('announced_at') and record.get('announced_at'):
                update['announced_at'] = record['announced_at']
            rounds.update_one({'_id': existing['_id']}, {'$set': update})
            return existing['_id'], 'merged'

    record['_id'] = round_id(record['company_key'], record.get('round'), record.get('announced_at'))
    rounds.replace_one({'_id': record['_id']}, record, upsert=True)
    return record['_id'], 'new'


STALE = {
    'type': 'article',
    '$or': [
        {'funding_hash': {'$exists': False}},
        {'$expr': {'$ne': ['$funding_hash', '$content_hash']}},
        {'funding_extraction_version': {'$ne': EXTRACTION_VERSION}},
    ],
}


def extract_stale(db, llm, model_name: str, limit: int = 40, force: bool = False) -> Dict[str, int]:
    """Run extraction on articles that look like funding news and have not
    been processed for their current text."""
    query = {'type': 'article'} if force else STALE
    stats = {'considered': 0, 'prefiltered_out': 0, 'extracted': 0, 'no_round': 0,
             'new': 0, 'merged': 0, 'failed': 0}
    articles = db[COLLECTION]

    for article in articles.find(query, {'embedding': 0, 'entities': 0}).sort('event_at', -1):
        if stats['extracted'] + stats['no_round'] + stats['failed'] >= limit:
            break
        stats['considered'] += 1
        title = article.get('title') or ''
        mark = {'funding_hash': article.get('content_hash'),
                'funding_extraction_version': EXTRACTION_VERSION}

        if not FUNDING_TITLE.search(title):
            stats['prefiltered_out'] += 1
            articles.update_one({'_id': article['_id']}, {'$set': {**mark, 'funding_round_id': None}})
            continue

        text = normalize_whitespace(f"{title}. {article.get('description') or ''}")[:1500]
        try:
            raw = llm.generate_json(
                prompt=PROMPT.format(title=title, text=text, rounds=', '.join(ROUND_NAMES)),
                system_prompt=SYSTEM_PROMPT, temperature=0.0)
            extracted = ExtractedRound.model_validate(raw)
        except (ValidationError, ValueError, Exception) as e:
            stats['failed'] += 1
            logger.warning(f"funding extraction failed for {title[:60]!r}: {e}")
            continue

        if not extracted.is_funding_round or not extracted.company:
            stats['no_round'] += 1
            articles.update_one({'_id': article['_id']}, {'$set': {**mark, 'funding_round_id': None}})
            continue

        record = to_record(extracted, article, text, model_name)
        rid, outcome = merge_into(db, record)
        stats[outcome] += 1
        stats['extracted'] += 1
        articles.update_one({'_id': article['_id']}, {'$set': {**mark, 'funding_round_id': rid}})

    db[FUNDING_ROUNDS].create_index('company_key')
    db[FUNDING_ROUNDS].create_index([('amount_usd', -1)])
    db[FUNDING_ROUNDS].create_index([('announced_at', -1)])
    return stats
