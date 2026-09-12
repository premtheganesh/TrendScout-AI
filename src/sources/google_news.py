"""
Google News RSS search. An aggregator: its stories are other outlets',
with " - Publisher" appended to titles and redirect links. Kept for
coverage of funding news TechCrunch and Crunchbase miss, but a story we
already have from its original outlet is skipped by title.
"""

import re
from typing import Any, Dict, Optional

from src.corpus.identity import name_key
from src.corpus.types import COLLECTION
from src.sources.rss import RSSSource

_PUBLISHER_SUFFIX = re.compile(r'\s+-\s+([^-]{2,60})$')


class GoogleNewsSource(RSSSource):
    def __init__(self, query: str = '"AI startup" raises when:7d', name: str = 'google_news'):
        from urllib.parse import quote_plus
        url = ('https://news.google.com/rss/search?q=' + quote_plus(query)
               + '&hl=en-US&gl=US&ceid=US:en')
        super().__init__(name=name, url=url, source_tag='googlenews', max_pages=1)

    def normalize(self, raw: Any) -> Optional[Dict[str, Any]]:
        doc = super().normalize(raw)
        if doc is None:
            return None
        match = _PUBLISHER_SUFFIX.search(doc['title'])
        if match:
            doc['publisher'] = match.group(1).strip()
            doc['title'] = doc['title'][:match.start()].strip()
            doc['title_key'] = name_key(doc['title'])
        # The description is the title wrapped in a link; nothing to keep.
        if doc.get('description', '').startswith(doc['title'][:30]):
            doc['description'] = ''
        return doc

    def is_duplicate(self, doc: Dict[str, Any], db) -> bool:
        if not doc.get('title_key'):
            return False
        return db[COLLECTION].find_one({
            'type': 'article', 'title_key': doc['title_key'],
            'source': {'$ne': self.source_tag},
        }, {'_id': 1}) is not None
