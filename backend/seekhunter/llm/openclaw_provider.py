import json
import subprocess
import uuid

from seekhunter.llm.base import LLMJobInput, LLMScore, LLMUnavailable
from seekhunter.llm.prompt import build_prompt, parse_batch_text
from seekhunter.profile import Profile

MAX_PROMPT_BYTES = 100_000


def _parse_envelope(stdout: str) -> dict:
    """Find the OpenClaw JSON envelope in stdout, ignoring log noise.

    Scans lines from the end for one that starts with "{" and parses on its own; falls back to
    `raw_decode` from the first "{" (tolerant of pretty-printed/multi-line JSON or trailing text).
    """
    for line in reversed(stdout.splitlines()):
        stripped = line.strip()
        if stripped.startswith("{"):
            try:
                return json.loads(stripped)
            except ValueError:
                continue
    start = stdout.find("{")
    if start < 0:
        raise LLMUnavailable("openclaw: no JSON object in output")
    try:
        envelope, _ = json.JSONDecoder().raw_decode(stdout, start)
    except ValueError as e:
        raise LLMUnavailable(f"openclaw: bad envelope: {e}") from e
    return envelope


class OpenClawProvider:
    """Uses OpenClaw's sandboxed, tool-less `seekhunter-scorer` agent (Codex via OpenAI OAuth), not the
    user's full-privilege `main` agent, since the prompt carries untrusted job-ad text. ~15 s per call,
    so callers batch jobs.
    """

    name = "openclaw"

    def __init__(self, bin_path: str = "openclaw", agent: str = "seekhunter-scorer",
                 timeout: int = 300) -> None:
        self.bin_path = bin_path
        self.agent = agent
        self.timeout = timeout

    def score_batch(self, profile: Profile, jobs: list[LLMJobInput]) -> dict[str, LLMScore]:
        system, user = build_prompt(profile, jobs)
        text = run_agent(f"{system}\n\n{user}", bin_path=self.bin_path, agent=self.agent,
                         timeout=self.timeout)
        return parse_batch_text(text)


def run_agent(prompt: str, *, bin_path: str = "openclaw", agent: str = "seekhunter-scorer",
              timeout: int = 300, thinking: str = "low", session_prefix: str = "seekhunter") -> str:
    """One OpenClaw agent turn in a fresh session; returns the final visible reply text.

    Raises `LLMUnavailable` on a too-large prompt, launch failure, timeout, non-zero exit, or an
    unparseable envelope.
    """
    if len(prompt.encode()) > MAX_PROMPT_BYTES:
        raise LLMUnavailable("openclaw: prompt too large for argv")
    cmd = [
        bin_path, "agent", "--agent", agent,
        "--session-id", f"{session_prefix}-{uuid.uuid4().hex[:12]}",
        "--thinking", thinking, "--json", "-m", prompt,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise LLMUnavailable(f"openclaw: {e}") from e
    if proc.returncode != 0:
        raise LLMUnavailable(f"openclaw exit {proc.returncode}: {proc.stderr[-300:]}")
    envelope = _parse_envelope(proc.stdout)
    try:
        text = envelope["result"]["meta"]["finalAssistantVisibleText"]
    except (KeyError, TypeError) as e:
        raise LLMUnavailable(f"openclaw: bad envelope: {e}") from e
    if not isinstance(text, str):
        raise LLMUnavailable("openclaw: reply text is not a string")
    return text
