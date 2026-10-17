import json
import subprocess
from datetime import date

from seekhunter.llm.base import LLMJobInput, LLMScore, LLMUnavailable
from seekhunter.llm.prompt import build_prompt, parse_batch_text
from seekhunter.profile import Profile


class OpenClawProvider:
    """Uses OpenClaw's gateway agent (Codex via OpenAI OAuth). ~15 s per call, so callers batch jobs."""

    name = "openclaw"

    def __init__(self, bin_path: str = "openclaw", timeout: int = 300) -> None:
        self.bin_path = bin_path
        self.timeout = timeout

    def score_batch(self, profile: Profile, jobs: list[LLMJobInput]) -> dict[str, LLMScore]:
        system, user = build_prompt(profile, jobs)
        cmd = [
            self.bin_path, "agent", "--agent", "main",
            "--session-id", f"seekhunter-{date.today().isoformat()}",
            "--thinking", "low", "--json", "-m", f"{system}\n\n{user}",
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise LLMUnavailable(f"openclaw: {e}") from e
        if proc.returncode != 0:
            raise LLMUnavailable(f"openclaw exit {proc.returncode}: {proc.stderr[-300:]}")
        start = proc.stdout.find("{")
        try:
            envelope = json.loads(proc.stdout[start:])
            text = envelope["result"]["meta"]["finalAssistantVisibleText"]
        except (ValueError, KeyError, TypeError) as e:
            raise LLMUnavailable(f"openclaw: bad envelope: {e}") from e
        return parse_batch_text(text)
