"""
Day 4 training lab: judge calibration, prompt comparison and repeat runs.

Run it from the repository root with `python -m training_day4 --help`.
It is isolated from the Day 3 lab (day3_lab) and only imports small,
compatible helpers from it. Nothing here changes Day 3 behaviour.

Module layout (one job per file):

- cli.py        -- argument parsing, printing, exit codes
- paths.py      -- where every input and the reports folder live
- config.py     -- model/credential configuration from environment variables
- data.py       -- loading cases, labels, policy rules, replay fixtures
- checks.py     -- the `validate` command's checks
- rules.py      -- the classroom pass rule, computed in code
- judge.py      -- what the judge sees, and validation of what it returns
- heuristics.py -- labelled, low-trust content flags (never a verdict)
- client.py     -- the OpenAI adapter: bounded retries, usage, redaction
- replay.py     -- teaching fixtures for --mode replay (no API calls)
- execute.py    -- the activities: judge, compare, repeat, calibrate, access-check
- runstore.py   -- immutable timestamped run folders, sanitising, human reviews
- markdown.py   -- readable Markdown tables for each report
"""
