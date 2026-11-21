"""python -m app.governance : try the Day 6 governed agent (deterministic, offline, no LLM)."""

from app.agent.cli import main

if __name__ == "__main__":
    raise SystemExit(main(governed=True))
