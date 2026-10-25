# Day 5 retrieval policy

> Synthetic training material for the AI QA Orchestration course. This file documents the Day 5 retrieval rules. It is **not** support knowledge, it lives outside `knowledge/day5/`, and it is never indexed.

**Python enforces these rules; this Markdown only documents them.** If the two ever disagree, the code in `training_day5/` is what actually runs, and this file needs fixing.

## 1. What the retriever receives

`retrieve()` in `training_day5/retriever.py` receives a **query**, an **OS value** and **top-k** (plus the loaded corpus). It never receives case IDs, expected document IDs, prohibited document IDs or whether a question is answerable, so it cannot use them. `retrieve --case R01` reads the query and OS from the case and passes only those two values and top-k.

## 2. Filtering (applied before scoring)

1. **Status.** Normal mode considers **approved** documents only. Obsolete documents are never candidates.
2. **OS.**
   - A **known OS** (`macos` or `windows`) permits documents for that OS **and** documents with `os: any`.
   - An **unknown OS** (for example `linux`), or `os: any`, permits documents with `os: any` **only**.
3. **Aliases.** OS values are normalised the same way everywhere: `mac`, `macOS`, `Mac OS`, `macintosh` become `macos`; `win`, `Windows 11` and similar become `windows`; `any`, `all`, `general`, `unknown` and an empty value become `any`. An unrecognised value stays as typed (lower-case) and is treated as unknown.

Metadata for this filtering comes from `knowledge/day5/manifest.json`, which is authoritative. Document text comes only from the Markdown files.

## 3. Ranking and scoring

Scores are **lexical** word-overlap counts. They are **not confidence probabilities**.

- **Tokenising.** Lower-case letters and digits. Document IDs such as `KB-VPN-MAC-CURRENT` are removed first, so an ID is never scored. A fixed stopword list is dropped. A trailing plural "s" is removed from words longer than three letters (`passwords` becomes `password`; `access` is left alone).
- **Score.** For each **distinct** query term: +1 if it appears in the document content (headings included) and +2 if it appears in the manifest title. The score is the sum.
- **Results.** Only documents with a **positive** score are returned. Order is highest score first, ties broken by `doc_id`. Results are unique, limited to top-k, and top-k must be a whole number of at least 1.

No case-specific rule exists anywhere in the retriever.

### Scoring limitations (kept, not hidden)

- There is no stemming beyond the plural "s" (so `approval` and `approved` do not match), no synonyms and no weighting by how rare a word is.
- A positive score does **not** establish that a document answers the question. A general document that shares a word with an unsupported question will be returned. For example, "How do I connect the VPN on Linux?" can retrieve the general VPN outage process because it contains the word "VPN". That failure is recorded as it happens.
- Mentioning a topic is not the same as covering it: a VPN guide that says "escalate" is not the escalation procedure.

## 4. Evaluation (document-level)

The scoring unit is the **document ID**. A document counts once if it is returned, whatever its rank.

- **Answerable case:** precision = relevant retrieved / retrieved count (0 when nothing is returned); recall = relevant retrieved / expected count. **PASS needs recall = 1 and no prohibited document.** Extra irrelevant documents lower precision but do not fail the case by themselves.
- **Unanswerable case:** precision and recall are N/A. **PASS needs zero retrieved documents.** A non-empty result means the retrieval abstention expectation failed; it is not proof that a model would hallucinate.
- **Aggregates:** macro precision and recall average the **answerable** cases only. Unanswerable successes and prohibited-document failures are reported separately.

This is a classroom gate, not a release decision. The labels in `datasets/day5/retrieval_cases.json` were written independently of retrieval output and must not be edited to make a report pass.

## 5. Synthetic fault handling

Faults exist to show what a retrieval failure looks like. All are **off by default**, are chosen per `evaluate` command with `--fault`, change only that command's in-memory results, and are never stored. Stored documents are never modified. Every fault run is labelled **SYNTHETIC FAULT INJECTION**.

| Fault | What it does |
| --- | --- |
| `obsolete-first` | If a positively scored current device-specific VPN guide was retrieved, puts its obsolete counterpart at rank 1, respecting top-k. |
| `wrong-os` | Replaces a current device-specific VPN guide with the opposite OS's current VPN guide. |
| `drop-required` | Evaluation harness only: removes one expected document that was retrieved, in the case's expected order. This deliberately uses the labels, and is kept separate from the retriever. |

If a fault's precondition is absent it is reported as **NOT APPLIED**, and nothing may be claimed from that run. The report records, per case and for the whole run, whether the fault was applied.

## 6. Reports

Each completed evaluation (including one with failing cases) is saved to a new folder, `reports/day5/<run_id>/`, as `results.json` and `report.md`. Existing runs are never overwritten. Each records the run ID, UTC time, mode `LOCAL_DETERMINISTIC`, fault mode and application status, Git commit and dirty state, knowledge-base, dataset and manifest hashes, retriever and evaluator versions, top-k, and for every case the query, OS, expected and retrieved IDs, lexical scores, missing IDs, prohibited matches, metrics, result and explanation.
