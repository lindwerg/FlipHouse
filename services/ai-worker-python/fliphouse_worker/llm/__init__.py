"""OpenRouter LLM adapter package (P2.2)."""

from .content_parts import text_part, video_part
from .engine_backend import EngineLLMBackend
from .openrouter_adapter import LLMResult, OpenRouterAdapter
from .routes import ROUTES, Profile, RouteConfig
from .schemas import VIRALITY_SCORE_SCHEMA

__all__ = [
    "ROUTES",
    "EngineLLMBackend",
    "LLMResult",
    "OpenRouterAdapter",
    "Profile",
    "RouteConfig",
    "VIRALITY_SCORE_SCHEMA",
    "text_part",
    "video_part",
]
