"""Groq API wrapper."""

import os
from groq import Groq
from dotenv import load_dotenv
import logging
import json
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class GroqClient:
    """Client for Groq LLM API"""

    # Tried in order when the configured model is unavailable.
    FALLBACK_MODELS = [
        "openai/gpt-oss-120b",
        "qwen/qwen3.8-27b",
        "qwen/qwen3.6-27b",
        "openai/gpt-oss-20b",
        "groq/compound",
    ]

    DEFAULT_MODEL = "openai/gpt-oss-120b"

    def __init__(self, model: str = None, verify: bool = True):
        """Initialize Groq client."""
        load_dotenv()

        api_key = os.getenv('GROQ_API_KEY')
        if not api_key:
            raise ValueError(
                "GROQ_API_KEY not found. Copy .env.example to .env and add "
                "a key from https://console.groq.com/keys"
            )

        self.client = Groq(api_key=api_key)
        requested = model or os.getenv('GROQ_MODEL') or self.DEFAULT_MODEL
        self.model = self._resolve_model(requested) if verify else requested

        logger.info(f"Groq client initialized with model: {self.model}")

    def available_models(self):
        """Model ids this API key can actually call."""
        try:
            return sorted(m.id for m in self.client.models.list().data)
        except Exception as e:
            logger.warning(f"Could not list Groq models: {e}")
            return []

    def _resolve_model(self, requested: str) -> str:
        """Return `requested` if Groq serves it, else the best fallback."""
        available = self.available_models()
        if not available:
            # Listing failed — assume the request is fine rather than
            # blocking startup on a transient error.
            return requested

        if requested in available:
            return requested

        for candidate in self.FALLBACK_MODELS:
            if candidate in available:
                logger.warning(
                    f"Groq model '{requested}' is not available on this "
                    f"account; falling back to '{candidate}'. "
                    f"Set GROQ_MODEL in .env to silence this."
                )
                return candidate

        raise ValueError(
            f"Groq model '{requested}' is unavailable and no fallback "
            f"matched. Models this key can reach: {', '.join(available)}"
        )
    
    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        reasoning_effort: Optional[str] = None
    ) -> str:
        """Generate text completion"""
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
        
        kwargs = {
            'model': self.model,
            'messages': messages,
            'temperature': temperature,
            'max_tokens': max_tokens,
        }
        if reasoning_effort:
            kwargs['reasoning_effort'] = reasoning_effort

        try:
            response = self.client.chat.completions.create(**kwargs)
        except Exception as e:
            # Some models reject reasoning_effort outright.
            if reasoning_effort and 'reasoning_effort' in str(e):
                kwargs.pop('reasoning_effort')
                response = self.client.chat.completions.create(**kwargs)
            else:
                logger.error(f"Groq API error: {e}")
                raise

        choice = response.choices[0]
        content = (choice.message.content or "").strip()

        if not content:
            if choice.finish_reason == 'length':
                raise RuntimeError(
                    f"Model '{self.model}' returned no visible output: the "
                    f"token budget ({max_tokens}) was consumed by reasoning "
                    f"tokens. Raise max_tokens or pass reasoning_effort='low'."
                )
            raise RuntimeError(
                f"Model '{self.model}' returned empty content "
                f"(finish_reason={choice.finish_reason})."
            )

        return content
    
    def generate_json(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.0
    ) -> Dict[str, Any]:
        """Generate structured JSON output"""
        if not system_prompt:
            system_prompt = "You are a helpful assistant that outputs valid JSON only."
        else:
            system_prompt += "\n\nYou must respond with valid JSON only. No markdown, no explanation."
        
        response_text = self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            reasoning_effort='low'
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


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(message)s')

    client = GroqClient()
    print("\nModels available to this API key:")
    for model_id in client.available_models():
        marker = "  ->" if model_id == client.model else "    "
        print(f"{marker} {model_id}")

    print(f"\nActive model: {client.model}")
    print("\nSmoke test:")
    print(client.generate(
        prompt="Reply with exactly: TrendScout AI is connected.",
        temperature=0.0,
        max_tokens=256,
        reasoning_effort='low',
    ))
