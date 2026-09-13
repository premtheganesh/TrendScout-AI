"""Retrieval-augmented generation: plan, retrieve, then answer with citations."""

import re
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Any

from src.corpus.types import DOC_TYPES, TYPE_NAMES, label_for, normalize_type
from src.llm.groq_client import GroqClient
from src.search.document_text import document_context, document_title, document_url

logger = logging.getLogger(__name__)

DEFAULT_CONTEXT_SIZE = 8

MAX_CHARS_PER_DOC = 900

MAX_SINCE_DAYS = 365
WIDEN_FACTOR = 4          # "last 7 days" -> "last 28 days" when nothing matches

INTENTS = ('search', 'funding_ranking')
FUNDING_DEFAULT_DAYS = 90

# gpt-oss models intermittently emit CJK bracket citations (【1】) instead of
# ASCII ones. The UI linkifies [n], so normalise before returning.
_CJK_CITATION = re.compile(r'【\s*(\d+)\s*】')


def normalize_citations(text: str) -> str:
    """Rewrite 【n】 style citations as [n]."""
    return _CJK_CITATION.sub(r'[\1]', text)


ANSWER_SYSTEM_PROMPT = """You are TrendScout AI, an analyst covering the AI \
startup ecosystem. You answer questions using ONLY the numbered sources \
provided to you.

Rules, in order of importance:

1. Ground every factual claim in the sources. After each claim, cite the \
source number in square brackets, like [2]. Cite multiple sources as [1][3] \
when several support the same claim.

2. If the sources do not contain the answer, say so plainly — for example \
"The indexed sources don't cover that." Then, if the sources contain \
something genuinely adjacent, offer it and label it as such. Never fill a \
gap with knowledge from your training data, and never guess at a funding \
figure, date, or investor name that is not written in a source.

3. If the sources disagree, say so and cite both.

4. Be concise and specific. Lead with the direct answer. Prefer concrete \
detail from the sources — names, locations, funding rounds, star counts — \
over generalities. Do not pad with caveats.

5. Write in plain prose or short bullets. Do not restate the question, and \
do not describe your own process."""

PLANNER_SYSTEM_PROMPT = """You turn a user's question about AI startups into \
a retrieval plan. Respond with JSON only."""


def _type_catalogue() -> str:
    width = max(len(name) for name in TYPE_NAMES) + 2
    return '\n'.join(
        f'  {json_quote(name):<{width}} - {DOC_TYPES[name].planner_hint}'
        for name in TYPE_NAMES
    )


def json_quote(value: str) -> str:
    return f'"{value}"'


def clamp_since_days(value) -> Optional[int]:
    """A positive number of days up to a year, or None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value > 0:
        return int(min(value, MAX_SINCE_DAYS))
    if isinstance(value, str) and value.strip().isdigit() and int(value) > 0:
        return int(min(int(value), MAX_SINCE_DAYS))
    return None


PLANNER_PROMPT = """Analyse this question and produce a retrieval plan.
Today is {today}.

{context_block}Available document types:
{type_catalogue}

If earlier conversation is shown above, resolve any reference the question
makes to it before writing the plan. "that city", "they", "the company",
"those" and similar must be replaced with the actual name from the earlier
turns, because the search engine sees only your search_query and has no
memory of the conversation.

Return JSON with exactly these keys:
{{
  "intent":       "search" or "funding_ranking" - "funding_ranking" only when
                             the question asks which companies raised the
                             most / the biggest rounds / ranks by amount.
  "search_query": string   - the query to send to the search engine. Strip
                             conversational filler and keep the substantive
                             terms. Expand obvious abbreviations, and
                             substitute referents with the names they point
                             to.
  "type":         string or null - one of the document type names above if
                             the question is clearly about only that kind of
                             thing, otherwise null.
  "location":     string or null - a city, state or country if the question
                             filters by place, otherwise null.
  "since_days":   integer or null - a time window in days when the question
                             asks about a period: "this week" / "recently"
                             -> 7, "this month" / "latest" -> 30, "this
                             year" -> 365. null when no period is implied.
}}

Examples:
Question: "What open source RAG frameworks are there?"
{{"intent": "search", "search_query": "open source retrieval augmented generation framework", "type": "repo", "location": null, "since_days": null}}

Question: "Which AI startups raised the most money this month?"
{{"intent": "funding_ranking", "search_query": "largest AI funding rounds", "type": "article", "location": null, "since_days": 30}}

Question: "Which AI startups in San Francisco raised Series B?"
{{"intent": "search", "search_query": "AI startup Series B funding", "type": "startup", "location": "San Francisco", "since_days": null}}

Question: "What's the latest news on AI coding tools?"
{{"intent": "search", "search_query": "AI coding tools developer", "type": "article", "location": null, "since_days": 30}}

Question: "Which AI startups launched this week?"
{{"intent": "search", "search_query": "AI startup launch", "type": "launch", "location": null, "since_days": 7}}

Question: "What funding rounds were announced last month?"
{{"intent": "search", "search_query": "AI startup raises funding round", "type": "article", "location": null, "since_days": 30}}

Question: "Tell me about Suno"
{{"intent": "search", "search_query": "Suno AI music generation", "type": null, "location": null, "since_days": null}}

With earlier conversation mentioning Suno in Cambridge, Massachusetts:
Question: "who else is in that city?"
{{"intent": "search", "search_query": "AI startup Cambridge Massachusetts", "type": "startup", "location": "Cambridge", "since_days": null}}

Now this question:
Question: "{question}"
JSON:"""


@dataclass
class Source:
    n: int
    doc_id: str
    type: str
    title: str
    url: str
    snippet: str
    rrf_score: float
    ranks: Dict[str, int] = field(default_factory=dict)
    shared_entities: List[str] = field(default_factory=list)


@dataclass
class RAGAnswer:
    question: str
    answer: str
    sources: List[Source]
    search_query: str
    plan: Dict[str, Any]
    used_llm_planner: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            'question': self.question,
            'answer': self.answer,
            'sources': [asdict(s) for s in self.sources],
            'search_query': self.search_query,
            'plan': self.plan,
            'used_llm_planner': self.used_llm_planner,
        }


class RAGPipeline:
    def __init__(
        self,
        search_engine,
        groq_client: Optional[GroqClient] = None,
        context_size: int = DEFAULT_CONTEXT_SIZE,
    ):
        self.search = search_engine
        self.context_size = context_size

        # A missing key disables answers but must not break retrieval.
        try:
            self.llm = groq_client or GroqClient()
            self.llm_available = True
        except Exception as e:
            logger.warning(f"Groq unavailable, answers disabled: {e}")
            self.llm = None
            self.llm_available = False

    # Stage 1 — understand
    def plan_query(
        self,
        question: str,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """
        Build a retrieval plan. History matters here, not just when
        generating: the search engine only ever sees `search_query`, so a
        follow-up like "who else is in that city?" retrieves nothing
        relevant unless the referent is resolved at this stage.
        """

        fallback = {
            'intent': 'search',
            'search_query': question,
            'type': None,
            'location': None,
            'since_days': None,
        }

        if not self.llm_available:
            return fallback

        context_block = ""
        if history:
            transcript = '\n'.join(
                f"{turn.get('role', 'user').capitalize()}: {turn.get('content', '')[:400]}"
                for turn in history[-4:] if turn.get('content')
            )
            if transcript:
                context_block = f"Earlier conversation:\n{transcript}\n\n"

        try:
            plan = self.llm.generate_json(
                prompt=PLANNER_PROMPT.format(
                    question=question,
                    context_block=context_block,
                    type_catalogue=_type_catalogue(),
                    today=self.today().isoformat(),
                ),
                system_prompt=PLANNER_SYSTEM_PROMPT,
                temperature=0.0,
            )
        except Exception as e:
            logger.warning(f"Query planning failed, using raw question: {e}")
            return fallback

        # Accept legacy collection names too; the model has seen them in
        # older transcripts.
        doc_type = normalize_type(plan.get('type') or plan.get('collection'))

        search_query = plan.get('search_query')
        if not isinstance(search_query, str) or not search_query.strip():
            search_query = question

        location = plan.get('location')
        if not isinstance(location, str) or not location.strip():
            location = None

        intent = plan.get('intent') if plan.get('intent') in INTENTS else 'search'

        return {
            'intent': intent,
            'search_query': search_query.strip(),
            'type': doc_type,
            'location': location,
            'since_days': clamp_since_days(plan.get('since_days')),
        }

    def today(self):
        return datetime.now(timezone.utc).date()

    # Stage 2 — retrieve
    def _filters(self, location: Optional[str], since_days: Optional[int]) -> Optional[Dict]:
        filters = {}
        if location:
            # Regex, since the corpus stores "Austin, Texas".
            filters['location'] = {'$regex': location, '$options': 'i'}
        if since_days:
            cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
            # Documents without a date never match a time window.
            filters['event_at'] = {'$gte': cutoff}
        return filters or None

    def retrieve(self, plan: Dict[str, Any], top_k: int) -> List[Dict]:
        """
        Search with the plan's constraints, relaxing them in a fixed order
        when nothing matches: drop the location first (it is the most
        often over-specific), then widen the time window, and only then
        drop the date. Every relaxation is recorded on the plan so the
        answer and the UI can say what was actually searched. The date
        constraint is never dropped silently: an empty result under
        "last 7 days" must not quietly become an answer about 2024.
        """
        location = plan.get('location')
        since_days = plan.get('since_days')

        ladder = [(location, since_days, None)]
        if location:
            ladder.append((None, since_days, 'dropped_location'))
        if since_days:
            widened = min(since_days * WIDEN_FACTOR, MAX_SINCE_DAYS)
            if widened > since_days:
                ladder.append((None, widened, f'widened_window_to_{widened}_days'))
            ladder.append((None, None, 'dropped_date'))

        plan['relaxations'] = []
        for loc, days, relaxation in ladder:
            if relaxation:
                plan['relaxations'].append(relaxation)
                logger.info(f"Nothing matched; relaxing: {relaxation}")
            results = self.search.search(
                query=plan['search_query'],
                doc_type=plan.get('type'),
                filters=self._filters(loc, days),
                top_k=top_k,
            )
            if results:
                plan['effective_location'] = loc
                plan['effective_since_days'] = days
                return results

        plan['effective_location'] = None
        plan['effective_since_days'] = None
        return []

    def retrieve_funding(self, plan: Dict[str, Any], top_k: int) -> List[Dict]:
        """
        The structured path for "who raised the most": a database query
        over extracted funding rounds sorted by amount, not a similarity
        search. Each row becomes a source pointing at the article it came
        from, with the round summary attached so the answer model sees
        the number the ranking used.
        """
        from bson import ObjectId
        from src.digest.select import round_summary

        db = self.search.mongo.db
        days = plan.get('since_days') or FUNDING_DEFAULT_DAYS
        query = {
            'confidence': {'$in': ['high', 'medium']},
            'amount_usd': {'$ne': None},
            'announced_at': {'$gte': datetime.now(timezone.utc) - timedelta(days=days)},
        }
        rounds = list(db.funding_rounds.find(query).sort([('amount_usd', -1), ('company', 1)]).limit(top_k))
        plan['effective_since_days'] = days
        plan['effective_location'] = None
        plan['relaxations'] = []
        if not rounds and days < MAX_SINCE_DAYS:
            query['announced_at'] = {'$gte': datetime.now(timezone.utc) - timedelta(days=MAX_SINCE_DAYS)}
            rounds = list(db.funding_rounds.find(query).sort([('amount_usd', -1), ('company', 1)]).limit(top_k))
            plan['relaxations'] = [f'widened_window_to_{MAX_SINCE_DAYS}_days']
            plan['effective_since_days'] = MAX_SINCE_DAYS if rounds else None

        results = []
        for rank, r in enumerate(rounds, start=1):
            doc = None
            for doc_id in r.get('source_doc_ids', []):
                if ObjectId.is_valid(doc_id):
                    doc = db.documents.find_one({'_id': ObjectId(doc_id)}, {'embedding': 0, 'entities': 0})
                    if doc:
                        break
            if doc is None:
                continue
            doc['_id'] = str(doc['_id'])
            doc['round_summary'] = round_summary(r)
            results.append({
                'doc_id': doc['_id'],
                'type': 'article',
                'rrf_score': 0.0,
                'ranks': {'funding': rank},
                'shared_entities': [],
                'document': doc,
                'title': f"{r.get('company')} — {round_summary(r)}",
                'url': document_url(doc, 'article'),
            })
        return results

    # Stage 3 — generate
    def build_context(self, results: List[Dict]) -> tuple:
        blocks, sources = [], []

        for i, result in enumerate(results, start=1):
            doc = result.get('document') or {}
            doc_type = result.get('type') or doc.get('type', '')
            title = result.get('title') or document_title(doc, doc_type)
            url = result.get('url') or document_url(doc, doc_type)
            body = document_context(doc, doc_type, max_chars=MAX_CHARS_PER_DOC)

            header = f"[{i}] {label_for(doc_type)}: {title}"
            block = [header, body]
            if url:
                block.append(f"Source URL: {url}")
            blocks.append('\n'.join(block))

            sources.append(Source(
                n=i,
                doc_id=result.get('doc_id', ''),
                type=doc_type,
                title=title,
                url=url,
                snippet=body[:280],
                rrf_score=round(float(result.get('rrf_score', 0.0)), 6),
                ranks=result.get('ranks', {}),
                shared_entities=result.get('shared_entities', []),
            ))

        return '\n\n'.join(blocks), sources

    def retrieval_note(self, plan: Dict[str, Any]) -> str:
        """One line telling the model what window was actually searched."""
        parts = [f"Today is {self.today().isoformat()}."]
        if plan.get('intent') == 'funding_ranking':
            parts.append("The sources are funding rounds already sorted by amount, "
                         "largest first; present them in that order and keep the amounts.")
        asked = plan.get('since_days')
        got = plan.get('effective_since_days')
        if asked and got and got != asked:
            parts.append(f"Nothing matched the last {asked} days, so the sources "
                         f"cover the last {got} days; say so.")
        elif asked and not got and plan.get('relaxations'):
            parts.append(f"Nothing matched the last {asked} days; the sources are "
                         "undated or older, so say the period is not covered.")
        elif got:
            parts.append(f"The sources are from the last {got} days.")
        if plan.get('location') and not plan.get('effective_location') and plan.get('relaxations'):
            parts.append(f"No source matched the location {plan['location']!r}; "
                         "say so rather than implying these are there.")
        return ' '.join(parts)

    def generate(
        self,
        question: str,
        context: str,
        history: Optional[List[Dict[str, str]]] = None,
        plan: Optional[Dict[str, Any]] = None,
    ) -> str:
        if not self.llm_available:
            return ("Answer generation is unavailable because GROQ_API_KEY is not "
                    "configured. The retrieved sources are listed below.")

        if not context.strip():
            kinds = ', '.join(label_for(t).lower() + 's' for t in TYPE_NAMES)
            return ("Nothing in the indexed corpus matches that question. "
                    f"The index covers {kinds}.")

        prompt_parts = []

        # History goes in as plain text so the "answer only from the
        # sources below" instruction stays next to the sources.
        if history:
            recent = history[-6:]
            transcript = '\n'.join(
                f"{turn.get('role', 'user').capitalize()}: {turn.get('content', '')}"
                for turn in recent if turn.get('content')
            )
            if transcript:
                prompt_parts.append(
                    f"Earlier in this conversation:\n{transcript}\n")

        prompt_parts.append(f"Sources:\n\n{context}\n")
        if plan:
            prompt_parts.append(f"Retrieval note: {self.retrieval_note(plan)}\n")
        prompt_parts.append(f"Question: {question}")
        prompt_parts.append(
            "Answer using only the sources above, citing them as [n].")

        try:
            return normalize_citations(self.llm.generate(
                prompt='\n'.join(prompt_parts),
                system_prompt=ANSWER_SYSTEM_PROMPT,
                temperature=0.2,   # low, but not 0 — this is prose, not JSON
                # Generous: on reasoning models the hidden trace is billed
                # against this budget, and a tight cap silently truncates
                # the visible answer to nothing.
                max_tokens=3000,
            )).strip()
        except Exception as e:
            logger.error(f"Answer generation failed: {e}")
            return (f"Retrieval succeeded but answer generation failed ({e}). "
                    "The sources below are still valid.")

    def answer(
        self,
        question: str,
        top_k: Optional[int] = None,
        history: Optional[List[Dict[str, str]]] = None,
        use_planner: bool = True,
    ) -> RAGAnswer:

        top_k = top_k or self.context_size

        if use_planner:
            plan = self.plan_query(question, history=history)
        else:
            plan = {'intent': 'search', 'search_query': question, 'type': None,
                    'location': None, 'since_days': None}

        if plan.get('intent') == 'funding_ranking':
            results = self.retrieve_funding(plan, top_k)
        else:
            results = self.retrieve(plan, top_k)
        context, sources = self.build_context(results)
        answer_text = self.generate(question, context, history=history, plan=plan)

        return RAGAnswer(
            question=question,
            answer=answer_text,
            sources=sources,
            search_query=plan['search_query'],
            plan=plan,
            used_llm_planner=use_planner and self.llm_available,
        )
