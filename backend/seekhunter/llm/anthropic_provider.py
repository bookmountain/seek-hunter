import anthropic

from seekhunter.llm.base import BatchFit, LLMJobInput, LLMScore, LLMUnavailable
from seekhunter.llm.prompt import build_prompt, to_scores
from seekhunter.profile import Profile

MODEL = "claude-haiku-4-5"


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, client: anthropic.Anthropic | None = None) -> None:
        self.client = client or anthropic.Anthropic(api_key=api_key, max_retries=2, timeout=90.0)

    def score_batch(self, profile: Profile, jobs: list[LLMJobInput]) -> dict[str, LLMScore]:
        system, user = build_prompt(profile, jobs)
        try:
            response = self.client.messages.parse(
                model=MODEL,
                max_tokens=2000,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=BatchFit,
            )
        except anthropic.APIError as e:  # 402 billing, 400 low credit, 401/403, 429 after retries, 5xx, network
            raise LLMUnavailable(f"anthropic: {e}") from e
        if response.parsed_output is None:
            raise LLMUnavailable("anthropic: no parsed output")
        return to_scores(response.parsed_output)
