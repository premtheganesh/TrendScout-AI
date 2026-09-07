"""LLM-Powered Data Normalizer"""

from src.llm.groq_client import GroqClient
from typing import Dict, Any, Optional
import logging
from pydantic import ValidationError

logger = logging.getLogger(__name__)


class DataNormalizer:
    """Normalize scraped data using LLM"""
    
    def __init__(self):
        """Initialize with Groq client"""
        self.llm = GroqClient()
        logger.info("Data normalizer initialized")
    
    def normalize_startup(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize YC Combinator startup data"""
        
        # Build prompt
        prompt = f"""
            Extract and normalize startup information from this raw data:

            {raw_data}

            Return a JSON object with these EXACT fields (use null if missing):
            - name: string (company name, cleaned)
            - description: string (clear description, 1-3 sentences)
            - website: string (full URL with https://)
            - yc_batch: string (format: W24, S23, F22, etc., uppercase)
            - founded_year: integer (4-digit year)
            - location: string (City, State or City, Country format)
            - tags: array of strings (relevant tech tags, max 5)

            Rules:
            1. Clean up whitespace and formatting
            2. Standardize location to "City, State/Country" format
            3. Convert YC batch to uppercase (e.g., "winter 2024" → "W24")
            4. Extract year from any date format
            5. Add https:// to URLs if missing
            6. Generate relevant tags based on description
            """
        
        try:
            result = self.llm.generate_json(
                prompt=prompt,
                system_prompt="You are a data normalization expert. Return valid, clean JSON.",
                temperature=0.0
            )
            
            logger.info(f"Normalized startup: {result.get('name')}")
            return result
            
        except Exception as e:
            logger.error(f"Failed to normalize startup: {e}")
            # Return original data as fallback
            return raw_data
    
    def normalize_article(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize TechCrunch article data"""
        
        prompt = f"""
            Extract and normalize article information from this raw data:

            {raw_data}

            Return a JSON object with these EXACT fields (use null if missing):
            - title: string (cleaned title, no extra formatting)
            - content: string (main article text, clean paragraphs)
            - url: string (full URL with https://)
            - author: string (author name)
            - published_date: string (ISO format: YYYY-MM-DDTHH:MM:SS)
            - source: string (default: "TechCrunch")
            - category: string (AI, Startups, Funding, etc.)
            - tags: array of strings (relevant tags, max 5)

            Rules:
            1. Clean HTML tags and extra whitespace
            2. Convert dates to ISO format
            3. Extract category from content/URL
            4. Generate relevant tags
            """
        
        try:
            result = self.llm.generate_json(
                prompt=prompt,
                system_prompt="You are a data normalization expert. Return valid, clean JSON.",
                temperature=0.0
            )
            
            logger.info(f"Normalized article: {result.get('title', '')[:50]}...")
            return result
            
        except Exception as e:
            logger.error(f"Failed to normalize article: {e}")
            return raw_data
    
    def normalize_repo(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize GitHub repository data"""
        
        prompt = f"""
            Extract and normalize GitHub repository information from this raw data:

            {raw_data}

            Return a JSON object with these EXACT fields (use null if missing):
            - name: string (repo name only, no username)
            - full_name: string (username/repo-name format)
            - description: string (cleaned description)
            - url: string (full GitHub URL)
            - stars: integer (star count)
            - forks: integer (fork count)
            - language: string (primary language)
            - topics: array of strings (GitHub topics/tags)
            - homepage: string (project homepage URL if exists)
            - created_at: string (ISO format date)
            - updated_at: string (ISO format date)

            Rules:
            1. Ensure stars and forks are integers (not strings)
            2. Clean and summarize description if too long
            3. Extract only relevant topics (max 10)
            """
        
        try:
            result = self.llm.generate_json(
                prompt=prompt,
                system_prompt="You are a data normalization expert. Return valid, clean JSON.",
                temperature=0.0
            )
            
            logger.info(f"Normalized repo: {result.get('full_name')}")
            return result
            
        except Exception as e:
            logger.error(f"Failed to normalize repo: {e}")
            return raw_data
    
    def enrich_description(self, description: str, context: str = "") -> str:
        """Enrich a description with better clarity and structure"""
        
        prompt = f"""
            Improve this description to be clearer and more informative:

            Original: {description}
            Context: {context}

            Rewrite to be:
            1. Clear and concise (2-3 sentences)
            2. Professional tone
            3. Highlight key features/value proposition
            4. Keep factual accuracy

            Return ONLY the improved description text, no JSON.
            """
        
        try:
            result = self.llm.generate(
                prompt=prompt,
                system_prompt="You are a professional copywriter. Improve the description.",
                temperature=0.3  # Slightly creative
            )
            
            return result.strip()
            
        except Exception as e:
            logger.error(f"Failed to enrich description: {e}")
            return description  # Return original on error
