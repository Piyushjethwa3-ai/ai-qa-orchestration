"""
Day 5 training lab: local document retrieval and independent retrieval evaluation.

Run it from the repository root with `python -m training_day5 --help`.
Everything here is local, deterministic and standard-library only: no model
calls, embeddings, vector database or network. It is separate from `day3_lab`
and `training_day4`, which are unchanged.

Module layout (one job per file):

- cli.py        -- argument parsing, printing, exit codes
- paths.py      -- where the knowledge base, cases, policy and reports live
- knowledge.py  -- manifest + Markdown loading, validation, safe paths, hashes
- retriever.py  -- the deterministic lexical retriever (sees query, OS, top-k only)
- cases.py      -- loading and validating the labelled retrieval cases
- metrics.py    -- precision, recall and the classroom pass gate (document IDs)
- faults.py     -- synthetic fault injection (off by default, per command only)
- evaluate.py   -- runs the cases through the retriever and scores them
- report.py     -- immutable run folders, results.json and report.md
- summary.py    -- `summary --run latest`
"""
