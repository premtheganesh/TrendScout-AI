from src.scrapers.base_scrapers import BaseScraper
from src.database.mongo_client import MongoDBClient
from bs4 import BeautifulSoup
import logging
from typing import Dict, List, Optional
from datetime import datetime
import re

logger = logging.getLogger(__name__)


class StartupSavantScraper(BaseScraper):
    """Scraper for startupsavant.com startup listings"""

    def __init__(self, headless: bool = True):
        """Initialize Startup Savant scraper"""
        super().__init__(headless)
        self.mongo = MongoDBClient()

    def extract_startup_data(self, h4_elem) -> Optional[Dict]:
        """Extract startup data starting from h4 company name element"""
        try:
            # Extract company name and remove numbering
            name = h4_elem.text.strip()
            # Remove pattern like "1. " or "23. " from start
            name = re.sub(r'^\d+\.\s*', '', name).strip()

            # Find the ul element that follows (contains metadata)
            ul_elem = h4_elem.find_next_sibling('ul')

            # Initialize data fields
            location = 'Unknown'
            funding = 'Unknown'
            investors = []

            # Extract metadata from list items
            if ul_elem:
                list_items = ul_elem.find_all('li')
                for li in list_items:
                    text = li.text.strip()

                    # Extract location
                    if 'location' in text.lower():
                        location = text.split(':', 1)[1].strip() if ':' in text else text

                    # Extract funding
                    elif 'funding' in text.lower() or 'series' in text.lower() or '$' in text:
                        funding = text.split(':', 1)[1].strip() if ':' in text else text

                    # Extract investors
                    elif 'investor' in text.lower():
                        investors_text = text.split(':', 1)[1].strip() if ':' in text else text
                        # Split by comma or 'and'
                        investors = [inv.strip() for inv in re.split(r',|and', investors_text)]

            # Extract description (paragraph after ul)
            description = 'No description'
            link = ''
            if ul_elem:
                p_elem = ul_elem.find_next_sibling('p')
                if p_elem:
                    description = p_elem.text.strip()
                    a_tag = p_elem.find('a')
                    link = a_tag.get('href') if a_tag else ''
            else:
                # Try finding p directly after h4
                p_elem = h4_elem.find_next_sibling('p')
                if p_elem:
                    description = p_elem.text.strip()

            data = {
                'name': name,
                'location': location,
                'funding': funding,
                'investors': investors,
                'description': description,
                'source': 'startupsavant',
                'scraped_at': datetime.utcnow().isoformat(),
                'link': link
            }

            return data

        except Exception as e:
            logger.error(f"Error extracting startup data: {e}")
            return None

    def scrape_startups_to_watch(self, limit: int = 1) -> int:
        """Scrape startups from startupsavant.com/startups-to-watch"""
        url = "https://startupsavant.com/startups-to-watch"

        logger.info(f"Scraping Startup Savant from {url}")

        # Navigate to page
        success = self.goto(url)
        if not success:
            logger.error("Failed to navigate to Startup Savant")
            return 0

        # Get HTML
        soup = self.get_html()

        # Find all h4 elements (company names)
        h4_elements = soup.find_all('h4')

        logger.info(f"Found {len(h4_elements)} potential startups")

        count = 0
        for h4 in h4_elements[:limit]:
            data = self.extract_startup_data(h4)

            if data and data['name'] and data['name'] != 'Unknown':
                try:
                    doc_id = self.mongo.insert_startup(data)
                    logger.info(f"Saved: {data['name']} - {data['location']}")
                    count += 1
                except Exception as e:
                    logger.error(f"Failed to save {data.get('name')}: {e}")

        logger.info(f"Scraped {count} startups from Startup Savant")
        return count

    def close(self):
        """Close browser and MongoDB connections"""
        self.stop()
        self.mongo.close()
        logger.info("StartupSavantScraper closed")