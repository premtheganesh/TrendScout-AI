"""
TechCrunch RSS Feed Scraper
Scrapes news articles from TechCrunch RSS feed
"""
import requests
from bs4 import BeautifulSoup
from src.database.mongo_client import MongoDBClient
import logging
from typing import Dict, List, Optional
from datetime import datetime
import re

logger = logging.getLogger(__name__)


class TechCrunchScraper:
    """Scraper for TechCrunch RSS feed"""

    def __init__(self):
        """Initialize TechCrunch scraper"""
        self.mongo = MongoDBClient()
        self.rss_url = "https://techcrunch.com/feed/"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }

    def extract_article_data(self, item) -> Optional[Dict]:
        """
        Extract article data from RSS feed item

        Args:
            item: BeautifulSoup element representing an RSS item

        Returns:
            Dict with article data or None
        """
        try:
            # Extract title
            title_elem = item.find('title')
            title = title_elem.text.strip() if title_elem else 'Unknown'

            # Extract link (article URL)
            link_elem = item.find('link')
            article_url = link_elem.text.strip() if link_elem else ''

            # Extract publication date
            pubdate_elem = item.find('pubDate')
            pub_date = pubdate_elem.text.strip() if pubdate_elem else ''

            # Extract description/summary
            # Description contains HTML, so we parse it to get clean text
            desc_elem = item.find('description')
            description = 'No description'
            if desc_elem:
                # Parse HTML content in description
                desc_soup = BeautifulSoup(desc_elem.text, 'html.parser')
                description = desc_soup.get_text().strip()

            # Extract author (creator in RSS)
            author_elem = item.find('dc:creator')
            author = author_elem.text.strip() if author_elem else 'Unknown'

            # Extract categories/tags
            category_elems = item.find_all('category')
            categories = [cat.text.strip() for cat in category_elems]

            # Try to extract company mentions from title
            # This is a simple approach - we'll enhance with NER later
            company_mentions = self._extract_company_mentions(title)

            data = {
                'title': title,
                'article_url': article_url,
                'published_date': pub_date,
                'description': description,
                'author': author,
                'categories': categories,
                'company_mentions': company_mentions,
                'source': 'techcrunch',
                'scraped_at': datetime.utcnow().isoformat()
            }

            return data

        except Exception as e:
            logger.error(f"Error extracting TechCrunch article: {e}")
            return None

    def _extract_company_mentions(self, text: str) -> List[str]:
        """
        Extract company mentions from text (simple pattern matching)
        This is a basic approach - will be enhanced with spaCy NER later

        Args:
            text: Text to extract company names from

        Returns:
            List of potential company names
        """
        # Common patterns for company names in headlines
        companies = []

        # Pattern: "Company raises/gets/secures $X"
        funding_pattern = r'([A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+)*)\s+(?:raises|gets|secures|lands|closes)'
        matches = re.findall(funding_pattern, text)
        companies.extend(matches)

        # Pattern: "Company's" or "Company is"
        possession_pattern = r"([A-Z][A-Za-z0-9]+(?:'s|\s+is|\s+has))"
        matches = re.findall(possession_pattern, text)
        companies.extend([m.replace("'s", '').replace(' is', '').replace(' has', '') for m in matches])

        # Remove duplicates and common false positives
        companies = list(set(companies))
        stop_words = ['The', 'This', 'That', 'These', 'Those', 'Here', 'There']
        companies = [c for c in companies if c not in stop_words]

        return companies

    def scrape_articles(self, limit: int = 10) -> int:
        """
        Scrape articles from TechCrunch RSS feed

        Args:
            limit: Maximum number of articles to scrape

        Returns:
            Number of articles successfully scraped
        """
        logger.info(f"Scraping TechCrunch RSS feed: {self.rss_url}")

        try:
            # Fetch RSS feed
            response = requests.get(self.rss_url, headers=self.headers, timeout=10)
            response.raise_for_status()

            # Parse XML
            soup = BeautifulSoup(response.content, 'xml')

            # Find all items (articles)
            items = soup.find_all('item', limit=limit)
            logger.info(f"Found {len(items)} articles in RSS feed")

            count = 0
            for item in items:
                data = self.extract_article_data(item)

                if data and data['title'] != 'Unknown':
                    try:
                        # Insert into MongoDB articles collection
                        doc_id = self.mongo.db.articles.insert_one(data).inserted_id
                        logger.info(f"✅ Saved: {data['title'][:60]}...")
                        count += 1
                    except Exception as e:
                        logger.error(f"Failed to save article: {e}")

            logger.info(f"Scraped {count} articles from TechCrunch")
            return count

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch RSS feed: {e}")
            return 0
        except Exception as e:
            logger.error(f"Error scraping TechCrunch: {e}")
            return 0

    def close(self):
        """Close MongoDB connection"""
        self.mongo.close()
        logger.info("TechCrunchScraper closed")