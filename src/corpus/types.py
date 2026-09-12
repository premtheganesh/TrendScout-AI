"""
Document type registry.

Every document lives in one MongoDB collection (`documents`) and carries a
`type`. This module is the single place that knows which types exist, how
they are labelled for people, prompts and Neo4j, and what they used to be
called when each type had its own collection. Nothing else should hardcode
'startup' / 'article' / 'repo'.
"""

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

COLLECTION = 'documents'


@dataclass(frozen=True)
class DocType:
    name: str                 # stored in doc['type']
    label: str                # human label: "News article"
    neo4j_label: str          # node label in the graph
    planner_hint: str         # one-line description for the query planner
    legacy_collection: str = ''   # pre-Phase-2 collection name, for migration


DOC_TYPES: Dict[str, DocType] = {t.name: t for t in (
    DocType(
        name='startup', label='Startup', neo4j_label='Startup',
        planner_hint='AI startup companies (name, description, location, funding, investors)',
        legacy_collection='startups',
    ),
    DocType(
        name='article', label='News article', neo4j_label='Article',
        planner_hint='news articles (title, description, author, categories)',
        legacy_collection='articles',
    ),
    DocType(
        name='repo', label='GitHub repository', neo4j_label='GitHubRepo',
        planner_hint='open-source repositories (name, description, language, topics, stars)',
        legacy_collection='github_repos',
    ),
)}

TYPE_NAMES: Tuple[str, ...] = tuple(DOC_TYPES)

LEGACY_COLLECTIONS: Dict[str, str] = {
    t.legacy_collection: t.name for t in DOC_TYPES.values() if t.legacy_collection
}

NEO4J_LABEL_TO_TYPE: Dict[str, str] = {
    t.neo4j_label: t.name for t in DOC_TYPES.values()
}


def normalize_type(value) -> Optional[str]:
    """A registered type name, from either its name or its legacy
    collection name. None for anything else."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if value in DOC_TYPES:
        return value
    return LEGACY_COLLECTIONS.get(value)


def label_for(type_name: str) -> str:
    doc_type = DOC_TYPES.get(type_name)
    return doc_type.label if doc_type else (type_name or 'Document')
