"""Bridge the OpenRouter adapter into the engine's ``llm_fn`` seam (P2-S2).

The highlight engine injects ``LLMFn = Callable[[str], str]`` and parses the
returned text loosely. :class:`EngineLLMBackend` satisfies that signature by
routing each prompt through :meth:`OpenRouterAdapter.complete`, while capturing
the model used and accumulating token usage for the per-job cost log (S7).
"""

from __future__ import annotations

from .openrouter_adapter import OpenRouterAdapter
from .routes import Profile


class EngineLLMBackend:
    """Adapts :class:`OpenRouterAdapter` to the engine's text ``llm_fn`` seam."""

    _USAGE_KEYS = ("prompt_tokens", "completion_tokens", "total_tokens")

    def __init__(self, adapter: OpenRouterAdapter, *, profile: Profile = Profile.SCORING) -> None:
        self._adapter = adapter
        self._profile = profile
        self.last_model_used: str = ""
        self.raw_usage: dict[str, int] = {}

    def __call__(self, prompt: str) -> str:
        result = self._adapter.complete(profile=self._profile, system="", user=prompt)
        self.last_model_used = result.model_used
        for key in self._USAGE_KEYS:
            self.raw_usage[key] = self.raw_usage.get(key, 0) + result.raw_usage.get(key, 0)
        return result.text
