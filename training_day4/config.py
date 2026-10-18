"""
Model and credential configuration for live mode.

Variables read (names only; values are never printed or stored):

- OPENAI_API_KEY      required for live mode
- OPENAI_MODEL        required for live mode; the response-generation model
- OPENAI_JUDGE_MODEL  optional; the judge model

If OPENAI_JUDGE_MODEL is not set, judging explicitly uses OPENAI_MODEL and
the configuration records that generation and judging use the same model.
No model name is invented, defaulted or substituted. No .env file is
loaded: only real environment variables are read. DAY4_MODEL is not used.
"""

import os
from dataclasses import dataclass, field


@dataclass
class Day4Config:
    api_key_configured: bool
    generation_model: str | None
    judge_model: str | None
    judge_model_source: str
    same_model: bool | None
    problems: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return not self.problems

    def models_record(self) -> dict:
        return {
            "generation": self.generation_model,
            "judge": self.judge_model,
            "judge_model_source": self.judge_model_source,
            "same_model_for_generation_and_judging": self.same_model,
        }


def load_config(env=None) -> Day4Config:
    env = os.environ if env is None else env
    key = (env.get("OPENAI_API_KEY") or "").strip()
    generation = (env.get("OPENAI_MODEL") or "").strip() or None
    judge_override = (env.get("OPENAI_JUDGE_MODEL") or "").strip() or None

    problems, notes = [], []
    if not key:
        problems.append("OPENAI_API_KEY is not set in this terminal's environment.")
    if not generation:
        problems.append("OPENAI_MODEL is not set. Set it to a model your API account can use; no default is chosen.")

    if judge_override:
        judge, source = judge_override, "OPENAI_JUDGE_MODEL"
    elif generation:
        judge, source = generation, "OPENAI_MODEL (OPENAI_JUDGE_MODEL is not set)"
        notes.append("Generation and judging use the same model. OPENAI_JUDGE_MODEL is not set.")
    else:
        judge, source = None, "unresolved"

    same = (generation == judge) if (generation and judge) else None
    if same and judge_override:
        notes.append("OPENAI_JUDGE_MODEL is set to the same model as OPENAI_MODEL; generation and judging use the same model.")
    if (env.get("DAY4_MODEL") or "").strip():
        notes.append("DAY4_MODEL is set but is not used. Day 4 reads OPENAI_MODEL and OPENAI_JUDGE_MODEL.")

    return Day4Config(
        api_key_configured=bool(key),
        generation_model=generation,
        judge_model=judge,
        judge_model_source=source,
        same_model=same,
        problems=problems,
        notes=notes,
    )
