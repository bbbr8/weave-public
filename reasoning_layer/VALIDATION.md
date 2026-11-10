# Historical evaluation record

The following measurements describe an earlier optional integration. The current
public profile executes local packets only and ships no model or remote transport.

# Reasoning layer validation

The reasoning layer is an experimental tool for making source interpretation and program execution inspectable. The retained trials exposed mistakes that would remain hidden behind an execution score: missing contract permissions, changing query meaning, and rejecting valid uncertainty answers. Version 0.3 addresses source accounting and records the judgments that connect each supplied passage to a program. Its source ledger describes review coverage; semantic correctness is measured separately.

| Retained trial | Direct once | Direct plus review | Language layer | Scope |
|---|---:|---:|---:|---|
| Build 0.1 | 20/24 | 20/24 | 18/24 | 12 selected public questions and 12 easy synthetic checks |
| Build 0.2 | 10/12 | 10/12 | 9/12 | Different cohort: 6 selected public questions and 6 easy synthetic checks |

| Public questions within those trials | Direct once | Language layer |
|---|---:|---:|
| Build 0.1 subset | 8/12 | 6/12 |
| Build 0.2 subset | 4/6 | 3/6 |

The cohorts differ and their sizes are small. Both comparisons favor the direct model. They establish no answer-accuracy advantage for the language layer. The earlier six-engine prepared-rule result measured execution correctness on a shared formalization. Native agreement concerns that program; interpretation of the original prose requires a separate assessment. A generic Python/SQL tool comparison is part of the stronger evaluation standard, rather than a completed experiment.

| Version 0.3 software checks | What the check establishes |
|---|---|
| 83 standard-library tests | Existing contract, arithmetic, review and recovery behavior plus 31 new source-accounting/compilation/recipe checks |
| Exact positional units | Every non-whitespace source character is retained once, including long Unicode spans |
| Ledger integrity | Missing/duplicate units, unknown references, mismatched quote links, unresolved representations and incomplete reviews produce diagnostics |
| Recorded review | Every unit and seven query facets receive an explicit decision; a model acceptance flag cannot bypass structural omissions |
| Derivation graph | Actual rule firings and premises are retained in a bounded graph; arithmetic identifies used and unused operands |
| Frozen replay | A changed source-unit artifact is detected before a cached result is reused |
| Native conjunction compilation | All 256 truth assignments for an eight-premise rule preserve the original closure. Collision handling and input preservation are tested. |
| Real native compilation check | All six engines execute both an eight-premise satisfied case and a seven-of-eight case: True and Unknown respectively; 12 executions agree with reference closure |
| Exact source recipe | A cached run rejects different package source; a change during execution preserves attempts without issuing completion |

The new tests are software behavior evidence. They include a deliberately wrong paraphrase with correct source links to demonstrate that structural accounting cannot certify semantic understanding. Lexical exception/time/negation cues highlight passages for review; they do not infer legal meaning. The model can still make an incorrect irrelevance judgment, and the same model's review is not an independent gold standard.

## Version 0.3 development check

One exposed prior public contract question and three authored synthetic diagnostics checked an exception, party roles/quoted instructions, and an exact posted balance. These are development diagnostics. Inputs and outputs were frozen before scoring; the original candidate's source snapshot and failures were preserved. All four tasks had complete structural source accounting and recorded reviews, covering 111 positional units and seven query facets per task. This records what the model considered; it does not independently verify each interpretation.

| Condition | Correct | Model calls | Summed model-call seconds |
|---|---:|---:|---:|
| Direct plus review | 4/4 | 2 | 33.82 |
| Retained 0.2 layer | 4/4 | 2 | 121.27 |
| Source-accounting candidate 0.3.0 | 3/4 | 2 | 646.77 |
| 0.3.1 execution replay of the same frozen programs/reviews | 4/4 | 0 new | Replay adds native execution, not new inference |

The initial candidate exposed a bridge mismatch: its valid seven-premise rule exceeded Accrete's six-premise input limit. Version 0.3.1 compiles the conjunction into equivalent smaller rules. Replaying all four frozen final programs produced the expected answers in 19 successful native executions. The separate eight-premise/missing-premise checks add 12 successful executions. The 4/4 replay is an engineering regression check on exposed programs, rather than a fresh model accuracy result. Numeric grading compares exact Decimal values in the declared unit and accepts an optional currency symbol.

The direct baseline already answered all four correctly. This diagnostic demonstrates source accounting and a repaired bridge, while the measured review cost increases substantially. Broader accuracy improvement remains an experimental hypothesis. The full combined repository suite passes 157 tests, comprising 74 retained Weave tests and 83 reasoning-layer tests.
