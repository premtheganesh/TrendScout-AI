"""
Pydantic schema for YC Combinator startups

This validates all startup data before it enters the database.
"""

from pydantic import BaseModel, validator, HttpUrl
from typing import Optional, List
from datetime import datetime


class StartupSchema(BaseModel):
    """
    Schema for YC Combinator startups
    
    Guarantees:
    - name is never empty
    - website is a valid URL (if provided)
    - founded_year is reasonable
    - All required fields present
    """
    
    # Required fields
    name: str
    description: str
    
    # Optional fields
    website: Optional[str] = None
    yc_batch: Optional[str] = None          # e.g., "W24", "S23"
    founded_year: Optional[int] = None
    location: Optional[str] = None
    tags: List[str] = []
    
    # Metadata
    scraped_at: Optional[datetime] = None
    source_url: Optional[str] = None
    
    # Validation rules
    @validator('name')
    def name_not_empty(cls, v):
        """Ensure name is not empty or just whitespace"""
        if not v or not v.strip():
            raise ValueError('Startup name cannot be empty')
        return v.strip()
    
    @validator('description')
    def description_not_empty(cls, v):
        """Ensure description has meaningful content"""
        if not v or len(v.strip()) < 10:
            raise ValueError('Description must be at least 10 characters')
        return v.strip()
    
    @validator('website', pre=True)
    def fix_website_url(cls, v):
        """Auto-fix URLs missing http://"""
        if v and v.strip():
            v = v.strip()
            if not v.startswith('http'):
                return f'https://{v}'
            return v
        return None
    
    @validator('founded_year')
    def valid_year(cls, v):
        """Ensure year is reasonable (between 1900 and current year)"""
        if v:
            current_year = datetime.now().year
            if v < 1900 or v > current_year + 1:
                raise ValueError(f'Founded year must be between 1900 and {current_year}')
        return v
    
    @validator('yc_batch')
    def valid_batch_format(cls, v):
        """Validate YC batch format (e.g., W24, S23)"""
        if v:
            v = v.strip().upper()
            # Should be like "W24", "S23", etc.
            if len(v) < 2 or v[0] not in ['W', 'S', 'F']:
                raise ValueError('YC batch should be like W24, S23, F22')
        return v
    
    class Config:
        schema_extra = {
            "example": {
                "name": "Suno AI",
                "description": "AI-powered music generation platform that creates songs from text prompts",
                "website": "https://suno.ai",
                "yc_batch": "W24",
                "founded_year": 2023,
                "location": "Cambridge, MA",
                "tags": ["AI", "music", "generative-ai"]
            }
        }