"""Pydantic schema for GitHub repositories"""

from pydantic import BaseModel, validator
from typing import Optional, List
from datetime import datetime


class RepoSchema(BaseModel):
    """Schema for GitHub repositories"""
    
    # Required fields
    name: str
    full_name: str  # e.g., "CompVis/stable-diffusion"
    url: str
    
    # Optional fields
    description: Optional[str] = None
    stars: int = 0
    forks: int = 0
    language: Optional[str] = None
    topics: List[str] = []
    homepage: Optional[str] = None
    
    # Dates
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    scraped_at: Optional[datetime] = None
    
    @validator('name')
    def name_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('Repo name cannot be empty')
        return v.strip()
    
    @validator('stars')
    def valid_stars(cls, v):
        if v < 0:
            raise ValueError('Stars cannot be negative')
        return v
    
    @validator('forks')
    def valid_forks(cls, v):
        if v < 0:
            raise ValueError('Forks cannot be negative')
        return v
    
    @validator('url', pre=True)
    def valid_url(cls, v):
        if v and 'github.com' not in v:
            raise ValueError('URL must be a GitHub URL')
        return v
    
    class Config:
        schema_extra = {
            "example": {
                "name": "stable-diffusion",
                "full_name": "CompVis/stable-diffusion",
                "description": "A latent text-to-image diffusion model",
                "url": "https://github.com/CompVis/stable-diffusion",
                "stars": 65000,
                "language": "Python",
                "topics": ["machine-learning", "deep-learning", "diffusion"]
            }
        }