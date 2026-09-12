"""
StartupSavant's yearly "startups to watch" list. Plain requests get a 403,
so this one drives a headless browser; it changes once a year, so it runs
monthly and never in CI.
"""

import logging
import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from bs4 import BeautifulSoup

from src.search.document_text import normalize_whitespace
from src.sources.base import Source

logger = logging.getLogger(__name__)

URL = 'https://startupsavant.com/startups-to-watch'
USER_AGENT = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')


def parse_page(html: str) -> List[Any]:
    """Company headings; each is normalised from its following siblings."""
    return BeautifulSoup(html, 'html.parser').find_all('h4')


class StartupSavantSource(Source):
    name = 'startupsavant'
    doc_type = 'startup'
    source_tag = 'startupsavant'
    schedule = 'monthly'
    default_window_days = None

    def fetch(self, since: Optional[datetime]) -> Iterable[Any]:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=['--no-sandbox'])
            try:
                page = browser.new_context(user_agent=USER_AGENT).new_page()
                page.goto(URL, timeout=60000, wait_until='domcontentloaded')
                page.wait_for_timeout(3000)
                html = page.content()
            finally:
                browser.close()
        headings = parse_page(html)
        logger.info(f"startupsavant: {len(headings)} headings")
        yield from headings

    def normalize(self, raw: Any) -> Optional[Dict[str, Any]]:
        name = re.sub(r'^\d+\.\s*', '', normalize_whitespace(raw.get_text())).strip()
        if not name:
            return None

        location, funding, investors = 'Unknown', 'Unknown', []
        ul = raw.find_next_sibling('ul')
        if ul:
            for li in ul.find_all('li'):
                text = normalize_whitespace(li.get_text())
                value = text.split(':', 1)[1].strip() if ':' in text else text
                lowered = text.lower()
                if 'location' in lowered:
                    location = value
                elif 'funding' in lowered or 'series' in lowered or '$' in text:
                    funding = value
                elif 'investor' in lowered:
                    investors = [i.strip() for i in re.split(r',|\band\b', value) if i.strip()]

        description, link = 'No description', ''
        paragraph = (ul or raw).find_next_sibling('p')
        if paragraph:
            description = normalize_whitespace(paragraph.get_text())
            anchor = paragraph.find('a')
            link = (anchor.get('href') or '').strip() if anchor else ''

        return {
            'name': name,
            'location': location,
            'funding': funding,
            'investors': investors,
            'description': description,
            'link': link,
        }
