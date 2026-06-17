"""OpenRouter LLM adapter package (P2.2)."""

from .content_parts import text_part, video_part
from .engine_backend import EngineHighlightBackend, EngineLLMBackend, HighlightFn
from .openrouter_adapter import LLMResult, OpenRouterAdapter
from .routes import ROUTES, Profile, RouteConfig
from .schemas import HIGHLIGHTS_SCHEMA, VIRALITY_SCORE_SCHEMA

__all__ = [
    "HIGHLIGHTS_SCHEMA",
    "ROUTES",
    "EngineHighlightBackend",
    "EngineLLMBackend",
    "HighlightFn",
    "LLMResult",
    "OpenRouterAdapter",
    "Profile",
    "RouteConfig",
    "VIRALITY_SCORE_SCHEMA",
    "text_part",
    "video_part",
]
