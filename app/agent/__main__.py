"""python -m app.agent : try the standalone Week 5 agent (deterministic, offline, no LLM)."""

from app.agent.cli import main

if __name__ == "__main__":
    raise SystemExit(main(governed=False))
