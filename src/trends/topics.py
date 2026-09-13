"""
Topic vocabulary for trends.

Topics come from the tags each source already carries — GitHub topics,
Hugging Face tags and paper keywords, YC tags and industries, article
categories, launch tags — normalised to one spelling. That vocabulary is
far cleaner than NER entities over one-line blurbs, which is why trends
are counted on topics and entities are only a secondary view.
"""

import re
from typing import Dict, Iterable, List

_NON_ALNUM = re.compile(r'[^a-z0-9]+')

# Spellings that mean the same thing.
ALIASES = {
    'llms': 'llm', 'large-language-model': 'llm', 'large-language-models': 'llm',
    'language-model': 'llm', 'language-models': 'llm',
    'genai': 'generative-ai', 'gen-ai': 'generative-ai',
    'artificial-intelligence': 'ai', 'machine-learning': 'ml', 'machinelearning': 'ml',
    'agents': 'agent', 'ai-agent': 'agent', 'ai-agents': 'agent', 'agentic-ai': 'agent',
    'agent-skill': 'agent-skills', 'skills': 'agent-skills', 'agent-skills': 'agent-skills',
    'agentic': 'agent', 'llm-agent': 'agent', 'llm-agents': 'agent', 'multi-agent': 'agent',
    'retrieval-augmented-generation': 'rag', 'rag-pipeline': 'rag',
    'chat-gpt': 'chatgpt', 'gpt4': 'gpt-4', 'text-to-speech': 'tts', 'speech-to-text': 'stt',
    'computer-vision': 'vision', 'cv': 'vision', 'nlp': 'nlp',
    'developer-tools': 'devtools', 'dev-tools': 'devtools', 'developer-tool': 'devtools',
    'open-source': 'open-source', 'opensource': 'open-source',
    'fine-tuning': 'finetuning', 'fine-tune': 'finetuning',
    'text-generation': 'text-generation', 'image-generation': 'image-generation',
}

# Too generic to mean anything in this corpus.
STOP_TOPICS = {
    'ai', 'python', 'typescript', 'javascript', 'saas', 'b2b', 'b2c', 'software', 'startup',
    'startups', 'technology', 'tech', 'platform', 'app', 'tool', 'tools', 'api', 'data',
    'open-source', 'ml', 'deep-learning', 'transformers', 'pytorch', 'safetensors',
    'region-us', 'endpoints-compatible', 'eval-results', 'license-mit', 'license-apache-2-0',
    'artificial-intelligence-ai', 'news', 'ai-news', 'fundraising', 'venture', 'funding',
    'know-how', 'text-generation', 'text-to-text', 'startups-news', 'startup-news', 'interviews',
    'events', 'other', 'misc', 'uncategorized', 'general', 'featured', 'europe',
}

# Publisher section tags such as 'uk-startups', 'italy-startups', 'ai-startups'.
_SECTION_TAG = re.compile(r'^([a-z]+-)?startups?$|^[a-z]+-(news|startups|weekly)$')

FIELDS_BY_TYPE = {
    'repo': ('topics',),
    'model': ('tags', 'pipeline_tag'),
    'paper': ('keywords',),
    'startup': ('tags', 'industries'),
    'launch': ('tags',),
    'article': ('categories',),
}


def normalize_topic(raw: str) -> str:
    if not isinstance(raw, str):
        return ''
    topic = _NON_ALNUM.sub('-', raw.strip().lower()).strip('-')
    topic = ALIASES.get(topic, topic)
    if not topic or len(topic) < 2 or topic in STOP_TOPICS or _SECTION_TAG.match(topic):
        return ''
    return topic


def document_topics(doc: Dict) -> List[str]:
    fields = FIELDS_BY_TYPE.get(doc.get('type', ''), ())
    seen, out = set(), []
    for field in fields:
        value = doc.get(field)
        values: Iterable = value if isinstance(value, list) else [value]
        for raw in values:
            topic = normalize_topic(raw)
            if topic and topic not in seen:
                seen.add(topic)
                out.append(topic)
    return out
