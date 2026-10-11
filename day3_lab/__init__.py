"""
Day 3 response-evaluation lab for the Northstar Services IT service desk.

Run it from the repository root with `python -m day3_lab <command>`.
See docs/day3_notes.md for the commands and what each module does.

Module layout (one job per file):

- cli.py         -- command-line parsing and printing (orchestration only)
- paths.py       -- where every input file lives
- dataset.py     -- loading and validating the cases, rubric and fixtures
- validation.py  -- structural checks on one response (JSON + schema)
- providers.py   -- where a response comes from: MOCK fixtures or LIVE OpenAI
- assessment.py  -- human review records and the outcome decision rule
- runner.py      -- builds run records for `run` and `clinic`
- report.py      -- writes run.json, run.html and clinic_notes.md
"""
