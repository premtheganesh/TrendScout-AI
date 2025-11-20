"""
Groq LLM Client

Wrapper for Groq API using Llama 3.3 70B for:
- Data normalization
- Text cleaning
- Structured output generation
"""

import os
from groq import Groq
from dotenv import load_dotenv
import logging
import json
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class GroqClient:
    """
    Client for Groq LLM API
    
    Uses Llama 3.3 70B Versatile model for:
    - Fast inference (fastest LLM platform)
    - High quality output
    - Structured data generation
    """
    
    def __init__(self, model: str = "llama-3.3-70b-versatile"):
        """
        Initialize Groq client
        
        Args:
            model: Model to use (default: llama-3.3-70b-versatile)
        """
        load_dotenv()
        
        api_key = os.getenv('GROQ_API_KEY')
        if not api_key:
            raise ValueError("GROQ_API_KEY not found in .env file")
        
        self.client = Groq(api_key=api_key)
        self.model = model
        
        logger.info(f"✅ Groq client initialized with model: {model}")
    
    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 1024
    ) -> str:
        """
        Generate text completion
        
        Args:
            prompt: User prompt
            system_prompt: System instructions (optional)
            temperature: 0.0 = deterministic, 1.0 = creative
            max_tokens: Maximum response length
            
        Returns:
            Generated text
        """
        messages = []
        
        if system_prompt:
            messages.append({
                "role": "system",
                "content": system_prompt
            })
        
        messages.append({
            "role": "user",
            "content": prompt
        })
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            logger.error(f"Groq API error: {e}")
            raise
    
    def generate_json(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.0
    ) -> Dict[str, Any]:
        """
        Generate structured JSON output
        
        Args:
            prompt: User prompt
            system_prompt: System instructions
            temperature: Sampling temperature
            
        Returns:
            Parsed JSON dictionary
        """
        if not system_prompt:
            system_prompt = "You are a helpful assistant that outputs valid JSON only."
        else:
            system_prompt += "\n\nYou must respond with valid JSON only. No markdown, no explanation."
        
        response_text = self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature
        )
        
        # Try to parse JSON
        try:
            # Remove markdown code blocks if present
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()
            
            return json.loads(response_text)
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON: {response_text}")
            raise ValueError(f"LLM did not return valid JSON: {e}")
