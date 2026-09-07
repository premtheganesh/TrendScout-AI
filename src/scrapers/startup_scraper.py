from src.scrapers.base_scrapers import BaseScraper
from src.database.mongo_client import MongoDBClient
from bs4 import BeautifulSoup
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class StartupScraper(BaseScraper):
    """Scraper for AI startup information"""
    
    def __init__(self, headless: bool = True):
        """Initialize startup scraper"""
        super().__init__(headless)
        self.mongo = MongoDBClient()
    
    def extract_company_data(self, soup: BeautifulSoup, url: str) -> Optional[Dict]:
        """Extract company data from page HTML"""
        try: 
            title = soup.find('title')
            h1 = soup.find('h1')
            first_p = soup.find('p')

            data = {
            'name': h1.text.strip() if h1 else 'Unknown',
            'description': first_p.text.strip() if first_p else 'No description',
            'url': url,
            'source': 'manual',
            'page_title': title.text.strip() if title else 'Unknown'
        }
            return data
        except Exception as e:
            logger.error(f"Error extracting data: {e}")
            return None
    
    def scrape_company(self, url: str) -> Optional[str]:
        """Scrape a single company page and save to MongoDB"""
        logger.info(f"Scraping {url}")
    
        # Navigate
        success = self.goto(url)
        if not success:
            return None
        
        # Get HTML
        soup = self.get_html()
        
        # Extract data
        data = self.extract_company_data(soup, url)
        if not data:
            return None
        
        # Save to MongoDB
        doc_id = self.mongo.insert_startup(data)
        logger.info(f"Saved company: {data['name']}")
        
        return doc_id
    
    def scrape_multiple(self, urls: list) -> int:
        """Scrape multiple company pages"""
        count = 0
    
        for url in urls:
            doc_id = self.scrape_company(url)
            if doc_id:
                count += 1
        
        logger.info(f"Scraped {count}/{len(urls)} companies")
        return count
    
    def close(self):
        """Close browser and MongoDB connections"""
        self.stop()  # Close browser (from BaseScraper)
        self.mongo.close()  # Close MongoDB
        logger.info("StartupScraper closed")