# Search a larger evidence collection

`evidence_search.py` builds a persistent SQLite FTS5 index and returns source-linked records. Python 3.12 with SQLite FTS5 is sufficient; there are no model downloads or paid API calls.

```sh
python tools/evidence_search.py --db evidence.sqlite index --input /path/to/records.jsonl --input /path/to/notes
python tools/evidence_search.py --db evidence.sqlite search 'invoice credit balance' --k 30
python tools/evidence_search.py --db evidence.sqlite expand 'what percentage of debt is current?' --max-records 64
python tools/evidence_search.py --db evidence.sqlite expand 'invoice credit balance' --where account=00017 --where version=v2 --before received=2026-11-04
python tools/evidence_search.py --db evidence.sqlite stats
```

The downloadable evaluation artifact contains an already-built public financial-report index. Run these commands against its `evidence.sqlite`, or build a separate index for other records.

## Inputs and more data

Import text/Markdown, CSV, or JSON/JSONL records. Duplicate JSON keys, duplicate CSV headers, malformed row widths and nonfinite JSON numbers are rejected rather than silently discarded. A folder is scanned for these file types. Text files are chunked with overlapping character spans. CSV rows keep field names and line locators. PDF and image extraction must be supplied separately.

For JSON/JSONL, each record has this form:

```json
{"id":"invoice-A:v2","parent_id":"invoice-A","text":"The source wording...","locator":"original/file#page=3","metadata":{"account":"00017","version":"v2","received":"2026-11-04","depends_on":["payment-A","credit-A"]}}
```

IDs must distinguish simultaneously retained source versions. Reimporting an existing ID updates that indexed record and invalidates its older citation hash. Conflicting duplicate IDs within one import are rejected atomically. Reimporting an existing native file removes chunks/rows that disappeared from that file. Files deleted outside the tool are not automatically discovered or removed; use `remove --id RECORD_ID` for explicit removal.

The index stays on disk between commands. Run `index` again with additional files to expand the collection. Private files stay in the index's local environment; this tool does not upload them, connect to Drive, or watch a remote computer.

## Search and follow-up retrieval

`search` applies explicit metadata filters inside the ranked SQL query, before its result limit. Leading-zero strings remain strings. `--before` filters a declared ISO date field; it does not infer when someone knew a fact. Records with missing date metadata do not satisfy that requested cutoff, and remain available in an unfiltered search.

`expand` first retrieves ten lexical hits, selects up to two parent documents, runs fixed follow-up searches for totals or balances when relevant query words occur, and reads surrounding parent records. It then follows explicitly declared `depends_on` links across documents, within the original metadata/date filters and depth/budget limits. Missing, excluded, budget-limited and depth-limited dependencies are returned separately. Query history can be supplied by concatenating earlier questions with the current one; answer text is unnecessary.

The default budget is 64 records and 64,000 source characters. `trace`, `budget` and `unresolved_dependencies` expose what was searched and what remains unavailable. Dependency completeness refers to supplied links, not every input that a real-world answer might require. Parent expansion and declared-link traversal do not infer semantic relationships or resolve conflicting claims.

Every hit includes original text, locator, metadata, exact snippet offsets, text hash and a hash binding the whole indexed record. `EvidenceIndex.validate_citation(hit)` checks whether that cited record still matches the current index. It does not verify a remote original that has changed without reimporting it. Scores are lexical ranks, not truth probabilities.

## Evaluation

The expanded evaluation indexes source prose/tables from every FinQA split plus ConvFinQA development reports. It excludes all questions, answer labels, programs, retrieved-gold fields and supporting-fact annotations from corpus construction.

The financial cohort contains 256 deterministically selected questions requiring at least two labeled evidence rows. Flat retrieval at 10 and 64 results is compared with expansion at the same 64-record/64,000-character budget; supplied-report scope is a separately labeled control. Conversational retrieval compares the latest question with prior-plus-current questions, using published per-turn support labels. No future turns or answers are supplied to search.

Sixty-four fictional ledger scenarios separately exercise 14 financial adjustments, four informational events, account/version distinctions, receipt cutoffs, missing records, subsequent import, conflicting reported claims and stale source references. Their relationships and accounting programs are declared structured inputs. They are mechanical controls, not measurements of natural-language case understanding.
