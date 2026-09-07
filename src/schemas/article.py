"""Pydantic schema for TechCrunch articles"""

from pydantic import BaseModel, validator, HttpUrl
from typing import Optional, List
from datetime import datetime


class ArticleSchema(BaseModel):
    """Schema for TechCrunch/news articles"""
    
    # Required fields
    title: str
    content: str
    url: str
    
    # Optional fields
    author: Optional[str] = None
    published_date: Optional[datetime] = None
    source: str = "TechCrunch"
    category: Optional[str] = None
    tags: List[str] = []
    
    # Metadata
    scraped_at: Optional[datetime] = None
    
    @validator('title')
    def title_not_empty(cls, v):
        if not v or len(v.strip()) < 10:
            raise ValueError('Title must be at least 10 characters')
        return v.strip()
    
    @validator('content')
    def content_not_empty(cls, v):
        if not v or len(v.strip()) < 50:
            raise ValueError('Content must be at least 50 characters')
        return v.strip()
    
    @validator('url', pre=True)
    def valid_url(cls, v):
        if v and not v.startswith('http'):
            raise ValueError('URL must start with http:// or https://')
        return v
    
    class Config:
        schema_extra = {
            "example": {
                "title": "Suno raises $125M for AI music generation",
                "content": "Suno, the AI music generation startup...",
                "url": "https://techcrunch.com/2024/05/21/suno-raises-125m",
                "author": "Kyle Wiggers",
                "published_date": "2024-05-21T10:00:00",
                "source": "TechCrunch",
                "tags": ["AI", "music", "funding"]
            }
        }