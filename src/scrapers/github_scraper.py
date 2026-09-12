"""GitHub Repository Scraper Scrapes trending AI repositories from GitHub API"""
import requests
from src.config import get_settings
from src.database.mongo_client import MongoDBClient
import logging
from typing import Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class GitHubScraper:
    """Scraper for GitHub trending AI repositories"""

    def __init__(self):
        """Initialize GitHub scraper"""
        self.mongo = MongoDBClient()
        self.api_url = "https://api.github.com/search/repositories"
        self.token = get_settings().github_token

        if not self.token or self.token == 'your_github_token_here':
            logger.warning("GitHub token not set. API rate limits will be lower.")

        self.headers = {
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }

        if self.token and self.token != 'your_github_token_here':
            self.headers["Authorization"] = f"Bearer {self.token}"

    def extract_repo_data(self, repo: Dict) -> Optional[Dict]:
        """Extract repository data from GitHub API response"""
        try:
            # Get primary language (may be None)
            primary_language = repo.get('language', 'Unknown')

            # Get topics/tags
            topics = repo.get('topics', [])

            # Get owner information
            owner = repo.get('owner', {})
            owner_name = owner.get('login', 'Unknown')
            owner_type = owner.get('type', 'Unknown')  # User or Organization

            # Build data structure
            data = {
                'name': repo.get('name', 'Unknown'),
                'full_name': repo.get('full_name', 'Unknown'),
                'description': repo.get('description', 'No description'),
                'html_url': repo.get('html_url', ''),
                'stars': repo.get('stargazers_count', 0),
                'forks': repo.get('forks_count', 0),
                'watchers': repo.get('watchers_count', 0),
                'open_issues': repo.get('open_issues_count', 0),
                'primary_language': primary_language,
                'topics': topics,
                'owner_name': owner_name,
                'owner_type': owner_type,
                'created_at': repo.get('created_at', ''),
                'updated_at': repo.get('updated_at', ''),
                'pushed_at': repo.get('pushed_at', ''),
                'homepage': repo.get('homepage', ''),
                'is_fork': repo.get('fork', False),
                'source': 'github',
                'scraped_at': datetime.utcnow().isoformat()
            }

            return data

        except Exception as e:
            logger.error(f"Error extracting GitHub repo data: {e}")
            return None

    def scrape_trending_repos(
        self,
        query: str = "topic:generative-ai topic:llm language:python",
        sort_by: str = "stars",
        limit: int = 10
    ) -> int:
        """Scrape trending AI repositories from GitHub"""
        logger.info(f"Searching GitHub for: '{query}'")

        params = {
            "q": query,
            "sort": sort_by,
            "order": "desc",
            "per_page": min(limit, 100)  # GitHub API max is 100
        }

        try:
            response = requests.get(
                self.api_url,
                headers=self.headers,
                params=params,
                timeout=10
            )

            # Check for rate limiting
            if response.status_code == 403:
                logger.error("GitHub API rate limit exceeded. Try again later or add a GitHub token.")
                return 0

            response.raise_for_status()

            data = response.json()

            if "items" not in data:
                logger.warning("No 'items' in API response")
                return 0

            repos = data["items"]
            total_count = data.get("total_count", 0)

            logger.info(f"Found {total_count} total repos, processing {len(repos)}")

            count = 0
            for repo in repos[:limit]:
                repo_data = self.extract_repo_data(repo)

                if repo_data:
                    try:
                        # Insert into MongoDB github_repos collection
                        doc_id = self.mongo.db.github_repos.insert_one(repo_data).inserted_id
                        logger.info(f"Saved: {repo_data['full_name']} ({repo_data['stars']} )")
                        count += 1
                    except Exception as e:
                        logger.error(f"Failed to save repo: {e}")

            logger.info(f"Scraped {count} repositories from GitHub")
            return count

        except requests.exceptions.HTTPError as http_err:
            if response.status_code == 401:
                logger.error("HTTP 401: Unauthorized. Check your GITHUB_TOKEN.")
            else:
                logger.error(f"HTTP error: {http_err}")
            return 0
        except Exception as e:
            logger.error(f"Error scraping GitHub: {e}")
            return 0

    def close(self):
        """Close MongoDB connection"""
        self.mongo.close()
        logger.info("GitHubScraper closed")
