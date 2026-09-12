"""
Write the digest. Citation numbers are assigned to the selected documents
first, globally across sections, and each section is generated with only
its own numbered sources. Every [n] the model writes is checked against
the numbers it was given; anything else is a fabrication and is stripped
and counted.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from src.corpus.types import label_for
from src.digest.select import SECTIONS, Selection
from src.rag.pipeline import normalize_citations
from src.search.document_text import document_context, document_title, document_url

logger = logging.getLogger(__name__)

PROMPT_VERSION = 'digest-v1'
DIGESTS = 'digests'

_CITATION = re.compile(r'\[(\d+)\]')
_BULLET = re.compile(r'^\s*[-*•]\s+')

SYSTEM_PROMPT = """You write the weekly TrendScout AI digest for people who follow \
the AI startup ecosystem. You use ONLY the numbered sources you are given.

Rules:
1. Every bullet states something concrete from a source and ends with its \
citation in square brackets, like [3]. Never write a bullet without a citation, \
and never cite a number you were not given.
2. Lead with names: the company, product, repository, model or paper. Include \
the numbers the sources give — amounts, rounds, stars, upvotes — and never invent any.
3. One bullet per item, at most {max_bullets} bullets, most notable first. \
Plain markdown bullets, no headings, no preamble, no closing remarks.
4. If the sources are thin, write fewer bullets. Never pad."""

SECTION_GUIDANCE = {
    'launches': "These are product launches and newly launched companies this week. Say what each one does.",
    'funding': "These are funding announcements this week. State who raised how much, the round, and the lead investors when given.",
    'open_source': "These are open-source repositories, models and papers that appeared this week. Say what each is for and why it is getting attention.",
}


def number_sources(selection: Selection) -> Tuple[Dict[str, List[Dict]], List[Dict]]:
    """Global [n] numbering, in section order. Returns per-section source
    lists and the flat list."""
    per_section: Dict[str, List[Dict]] = {}
    flat: List[Dict] = []
    n = 0
    for key, _ in SECTIONS:
        entries = []
        for doc in selection.sections.get(key, []):
            n += 1
            doc_type = doc.get('type', '')
            entries.append({
                'n': n,
                'doc_id': str(doc['_id']),
                'type': doc_type,
                'title': document_title(doc, doc_type),
                'url': document_url(doc, doc_type),
                'event_at': doc.get('event_at'),
                # Short on purpose: the free Groq tier allows 8k tokens/minute
                # and a section prompt must fit in one call.
                'context': document_context(doc, doc_type, max_chars=320),
            })
        per_section[key] = entries
        flat.extend(entries)
    return per_section, flat


def section_prompt(key: str, sources: List[Dict]) -> str:
    blocks = [f"[{s['n']}] {label_for(s['type'])}: {s['title']}\n{s['context']}"
              + (f"\nSource URL: {s['url']}" if s['url'] else '')
              for s in sources]
    return (f"{SECTION_GUIDANCE[key]}\n\nSources:\n\n" + '\n\n'.join(blocks)
            + "\n\nWrite the bullets now, citing each as [n].")


def validate(markdown: str, allowed: set) -> Tuple[str, Dict[str, int]]:
    """Strip citations the model was not given; count uncited bullets."""
    stats = {'invalid_citations': 0, 'uncited_bullets': 0, 'bullets': 0}

    def keep(match):
        if int(match.group(1)) in allowed:
            return match.group(0)
        stats['invalid_citations'] += 1
        return ''

    cleaned_lines = []
    for line in normalize_citations(markdown).splitlines():
        line = _CITATION.sub(keep, line).rstrip()
        if _BULLET.match(line):
            stats['bullets'] += 1
            if not _CITATION.search(line):
                stats['uncited_bullets'] += 1
        cleaned_lines.append(line)
    return '\n'.join(cleaned_lines).strip(), stats


def generate_section(llm, key: str, sources: List[Dict], max_bullets: int) -> Tuple[str, Dict[str, int]]:
    if not sources:
        return '', {'invalid_citations': 0, 'uncited_bullets': 0, 'bullets': 0}
    text = llm.generate(
        prompt=section_prompt(key, sources),
        system_prompt=SYSTEM_PROMPT.format(max_bullets=max_bullets),
        temperature=0.2,
        max_tokens=2500,
    )
    return validate(text, {s['n'] for s in sources})


def build_digest(selection: Selection, llm, model_name: str) -> Dict[str, Any]:
    per_section, flat = number_sources(selection)
    sections = []
    warnings: Dict[str, int] = {'invalid_citations': 0, 'uncited_bullets': 0}
    for key, title in SECTIONS:
        sources = per_section[key]
        markdown, stats = generate_section(llm, key, sources, max_bullets=min(len(sources), 12) or 1)
        warnings['invalid_citations'] += stats['invalid_citations']
        warnings['uncited_bullets'] += stats['uncited_bullets']
        sections.append({
            'key': key,
            'title': title,
            'markdown': markdown,
            'bullets': stats['bullets'],
            'sources': [{k: v for k, v in s.items() if k != 'context'} for s in sources],
        })

    return {
        '_id': selection.week,
        'week': selection.week,
        'week_start': selection.start,
        'week_end': selection.end,
        'generated_at': datetime.now(timezone.utc),
        'model': model_name,
        'prompt_version': PROMPT_VERSION,
        'input_hash': selection.input_hash,
        'input_doc_ids': [s['doc_id'] for s in flat],
        'counts': {key: len(per_section[key]) for key, _ in SECTIONS},
        'sections': sections,
        'warnings': warnings,
    }


def generate_week(db, week: str, start: datetime, end: datetime, llm,
                  model_name: str, force: bool = False) -> Tuple[Optional[Dict[str, Any]], str]:
    """Returns (digest, status) where status is 'generated', 'unchanged'
    or 'empty'. 'unchanged' means the stored digest was built from exactly
    these inputs, so no model call was made."""
    from src.digest.select import select_week
    selection = select_week(db, week, start, end)
    if not selection.documents:
        return None, 'empty'

    existing = db[DIGESTS].find_one({'_id': week})
    if existing and not force and existing.get('input_hash') == selection.input_hash \
            and existing.get('prompt_version') == PROMPT_VERSION:
        return existing, 'unchanged'

    digest = build_digest(selection, llm, model_name)
    db[DIGESTS].replace_one({'_id': week}, digest, upsert=True)
    return digest, 'generated'
