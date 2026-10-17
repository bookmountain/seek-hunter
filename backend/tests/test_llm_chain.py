from seekhunter.llm.base import LLMJobInput, LLMScore, LLMUnavailable
from seekhunter.llm.chain import LLMChain
from seekhunter.llm.prompt import build_prompt, parse_batch_text
from seekhunter.profile import Profile

PROFILE = Profile(skills={"React"}, summary="Full-stack engineer", titles=["Software Engineer"],
                  skill_lines=["Languages: TypeScript"], bullets=["Built things"])
JOBS = [LLMJobInput(key="1", title="Dev", company="A", work_type="contract", text="React role")]


class Dead:
    name = "dead"

    def __init__(self):
        self.calls = 0

    def score_batch(self, profile, jobs):
        self.calls += 1
        raise LLMUnavailable("out of credit")


class Good:
    name = "good"

    def score_batch(self, profile, jobs):
        return {j.key: LLMScore(fit=77, why="fits") for j in jobs}


def test_chain_falls_through_and_remembers_dead_provider():
    dead = Dead()
    chain = LLMChain([dead, Good()])
    scores, provider = chain.score_batch(PROFILE, JOBS)
    assert provider == "good" and scores["1"].fit == 77
    chain.score_batch(PROFILE, JOBS)
    assert dead.calls == 1


def test_chain_all_unavailable_returns_empty():
    assert LLMChain([Dead()]).score_batch(PROFILE, JOBS) == ({}, None)
    assert LLMChain([]).score_batch(PROFILE, JOBS) == ({}, None)


def test_prompt_contains_profile_and_keys():
    system, user = build_prompt(PROFILE, JOBS)
    assert "student visa" in system.lower()
    assert '"key": "1"' in user and "Full-stack engineer" in user


def test_parse_batch_text_extracts_json_from_noise():
    raw = 'Sure!\n{"results": [{"key": "1", "fit": 150, "why": "great"}]}\nThanks'
    out = parse_batch_text(raw)
    assert out["1"].fit == 100 and out["1"].why == "great"
