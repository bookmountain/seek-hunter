import logging

from seekhunter.config import Env
from seekhunter.llm.base import LLMJobInput, LLMProvider, LLMScore, LLMUnavailable
from seekhunter.profile import Profile
from seekhunter.settings_model import AppSettings

log = logging.getLogger(__name__)


class LLMChain:
    def __init__(self, providers: list[LLMProvider]) -> None:
        self.providers = providers
        self._dead: set[str] = set()

    def score_batch(self, profile: Profile, jobs: list[LLMJobInput]) -> tuple[dict[str, LLMScore], str | None]:
        for provider in self.providers:
            if provider.name in self._dead:
                continue
            try:
                return provider.score_batch(profile, jobs), provider.name
            except LLMUnavailable as e:
                log.warning("LLM provider %s unavailable: %s", provider.name, e)
                self._dead.add(provider.name)
        return {}, None


def build_chain(settings: AppSettings, env: Env) -> LLMChain:
    if not settings.llm_enabled:
        return LLMChain([])
    providers: list[LLMProvider] = []
    for name in settings.llm_providers:
        if name == "anthropic" and env.anthropic_api_key:
            from seekhunter.llm.anthropic_provider import AnthropicProvider

            providers.append(AnthropicProvider(env.anthropic_api_key))
        elif name == "openclaw":
            from seekhunter.llm.openclaw_provider import OpenClawProvider

            providers.append(OpenClawProvider(env.openclaw_bin))
    return LLMChain(providers)
