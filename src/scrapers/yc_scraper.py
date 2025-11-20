from src.scrapers.base_scrapers import BaseScraper
from src.database.mongo_client import MongoDBClient
from bs4 import BeautifulSoup
import logging
from typing import Dict, List, Optional
from datetime import datetime
import re

logger = logging.getLogger(__name__)


class YCombinatorScraper(BaseScraper):
    """Scraper for Y Combinator AI companies directory"""

    def __init__(self, headless: bool = True):
        """Initialize YC scraper"""
        super().__init__(headless)
        self.mongo = MongoDBClient()
        self.base_url = "https://www.ycombinator.com"

    def extract_company_card(self, card) -> Optional[Dict]:
        """
        Extract company data from a YC company card

        Args:
            card: BeautifulSoup element representing a company card (an <a> tag)

        Returns:
            Dict with company data or None
        """
        try:
            # Extract company name
            # Looking for <span> with class containing '_coName'
            name_elem = card.find('span', class_=lambda x: x and '_coName' in x)
            name = name_elem.text.strip() if name_elem else 'Unknown'

            # Extract location
            # Looking for <span> with class containing '_coLocation'
            location_elem = card.find('span', class_=lambda x: x and '_coLocation' in x)
            location = location_elem.text.strip() if location_elem else 'Unknown'

            # Extract description
            # Looking for <div class="mb-1.5 text-sm"> then <span> inside it
            desc_div = card.find('div', class_='mb-1.5 text-sm')
            description = 'No description'
            if desc_div:
                desc_span = desc_div.find('span')
                if desc_span:
                    description = desc_span.text.strip()

            # Extract company URL
            # The card itself is an <a> tag with href like "/companies/item"
            href = card.get('href', '')
            company_url = f"https://www.ycombinator.com{href}" if href else ''

            # Extract YC batch (e.g., "Fall 2025", "W23")
            # Looking for <a> tag with class containing '_tagLink' - first one is usually batch
            batch_link = card.find('a', class_=lambda x: x and '_tagLink' in x)
            yc_batch = batch_link.text.strip() if batch_link else 'Unknown'

            # Extract tags/categories
            # Find all <a> tags with '_tagLink' class - skip first (batch), rest are tags
            tag_links = card.find_all('a', class_=lambda x: x and '_tagLink' in x)
            tags = []
            if len(tag_links) > 1:
                # Skip first link (batch), extract rest as tags
                tags = [tag.text.strip() for tag in tag_links[1:]]

            data = {
                'name': name,
                'description': description,
                'yc_batch': yc_batch,
                'location': location,
                'tags': tags,
                'company_url': company_url,
                'source': 'ycombinator',
                'scraped_at': datetime.utcnow().isoformat()
            }

            return data

        except Exception as e:
            logger.error(f"Error extracting YC card: {e}")
            return None

    def scrape_yc_ai_companies(self, limit: int = 10) -> int:
        """
        Scrape AI companies from Y Combinator directory

        Args:
            limit: Maximum number of companies to scrape

        Returns:
            Number of companies successfully scraped
        """
        # Use the filtered URL with B2B and recent batches
        url = "https://www.ycombinator.com/companies?batch=Fall%202025&batch=Summer%202025&batch=Spring%202025&batch=Winter%202025&industry=B2B&regions=United%20States%20of%20America"

        logger.info(f"Scraping YC companies from {url}")

        # Navigate to page
        success = self.goto(url)
        if not success:
            logger.error("Failed to navigate to YC page")
            return 0

        # Get HTML
        soup = self.get_html()

        # Find all company cards
        # Each company is an <a> tag with class containing '_company'
        cards = soup.find_all('a', class_=lambda x: x and '_company' in x, limit=limit)

        logger.info(f"Found {len(cards)} company cards")

        count = 0
        for card in cards[:limit]:
            data = self.extract_company_card(card)

            if data and data['name'] != 'Unknown':
                try:
                    doc_id = self.mongo.insert_startup(data)
                    logger.info(f"✅ Saved: {data['name']} ({data.get('yc_batch', 'N/A')})")
                    count += 1
                except Exception as e:
                    logger.error(f"Failed to save {data.get('name')}: {e}")

        logger.info(f"Scraped {count} companies from YC")
        return count

    def close(self):
        """Close browser and MongoDB connections"""
        self.stop()
        self.mongo.close()
        logger.info("YCombinatorScraper closed")