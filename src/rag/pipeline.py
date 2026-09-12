"""Retrieval-augmented generation: plan, retrieve, then answer with citations."""

import re
import logging
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any

from src.corpus.types import DOC_TYPES, TYPE_NAMES, label_for, normalize_type
from src.llm.groq_client import GroqClient
from src.search.document_text import document_text, document_title, document_url

logger = logging.getLogger(__name__)

DEFAULT_CONTEXT_SIZE = 8

MAX_CHARS_PER_DOC = 900

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


PLANNER_PROMPT = """Analyse this question and produce a retrieval plan.

{context_block}Available document types:
{type_catalogue}

If earlier conversation is shown above, resolve any reference the question
makes to it before writing the plan. "that city", "they", "the company",
"those" and similar must be replaced with the actual name from the earlier
turns, because the search engine sees only your search_query and has no
memory of the conversation.

Return JSON with exactly these keys:
{{
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
}}

Examples:
Question: "What open source RAG frameworks are there?"
{{"search_query": "open source retrieval augmented generation framework", "type": "repo", "location": null}}

Question: "Which AI startups in San Francisco raised Series B?"
{{"search_query": "AI startup Series B funding", "type": "startup", "location": "San Francisco"}}

Question: "What's the latest news on AI coding tools?"
{{"search_query": "AI coding tools developer", "type": "article", "location": null}}

Question: "Tell me about Suno"
{{"search_query": "Suno AI music generation", "type": null, "location": null}}

With earlier conversation mentioning Suno in Cambridge, Massachusetts:
Question: "who else is in that city?"
{{"search_query": "AI startup Cambridge Massachusetts", "type": "startup", "location": "Cambridge"}}

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
            'search_query': question,
            'type': None,
            'location': None,
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

        return {
            'search_query': search_query.strip(),
            'type': doc_type,
            'location': location,
        }

    # Stage 2 — retrieve
    def retrieve(self, plan: Dict[str, Any], top_k: int) -> List[Dict]:
        filters = None
        if plan.get('location'):
            # Regex, since the corpus stores "Austin, Texas".
            filters = {'location': {'$regex': plan['location'], '$options': 'i'}}

        results = self.search.search(
            query=plan['search_query'],
            doc_type=plan.get('type'),
            filters=filters,
            top_k=top_k,
        )

        # A location filter that matches nothing should not produce an empty
        # answer — retry unfiltered and let the model note the mismatch.
        if not results and filters:
            logger.info("Location filter matched nothing; retrying unfiltered")
            results = self.search.search(
                query=plan['search_query'],
                doc_type=plan.get('type'),
                top_k=top_k,
            )

        return results

    # Stage 3 — generate
    def build_context(self, results: List[Dict]) -> tuple:
        blocks, sources = [], []

        for i, result in enumerate(results, start=1):
            doc = result.get('document') or {}
            doc_type = result.get('type') or doc.get('type', '')
            title = result.get('title') or document_title(doc, doc_type)
            url = result.get('url') or document_url(doc, doc_type)
            body = document_text(doc, doc_type)[:MAX_CHARS_PER_DOC]

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

    def generate(
        self,
        question: str,
        context: str,
        history: Optional[List[Dict[str, str]]] = None,
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
            plan = {'search_query': question, 'type': None, 'location': None}

        results = self.retrieve(plan, top_k)
        context, sources = self.build_context(results)
        answer_text = self.generate(question, context, history=history)

        return RAGAnswer(
            question=question,
            answer=answer_text,
            sources=sources,
            search_query=plan['search_query'],
            plan=plan,
            used_llm_planner=use_planner and self.llm_available,
        )
