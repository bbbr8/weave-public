# Reasoning layer 0.3.1

A Python CLI and library for source-linked model programs. A model writes a sourced program; the layer checks question identity, typed query features, source spans and answer coverage; an execution backend runs it; one optional model review receives the full source, diagnostics and execution result. Version 0.3 adds a positional record for every source passage and an inspectable graph of the actual derivation. Original and revised programs remain separate artifacts.

| Component | Implemented behavior |
|---|---|
| Question preservation | Frozen question/context hashes, caller query signature, matching goals, and a review diagnostic for added requirement language. |
| Source checks | Every asserted fact cites an exact context substring. Resolved character spans and source hashes are retained. Matching quotes establish location, not semantic entailment. |
| Whole-source accounting | Every positional source unit receives a represented, irrelevant or unresolved disposition, a reason and validated program references. All non-whitespace text is accounted for. Missing units, unknown references and quote/link mismatches produce explicit diagnostics. |
| Source review | The reviewer records its decision for every unit and seven query facets: actors, predicate, modality, quantifiers, polarity, time/scope, exceptions/conditions. Lexical risk cues highlight potentially consequential omissions for review. |
| Reasoning trace | A bounded graph records reached goals, source facts, actual rule firings and their premises/source units. Arithmetic records the formula, sourced operands and which operands it uses. |
| Native compilation | Seven/eight-premise conjunctions are split into equivalent rules of at most six premises. Auxiliary symbols are collision-checked; full compiled closure and projection onto original symbols are verified. |
| Answer policies | Caller-owned truth/choice/numeric policy. Support, refutation, undetermined and inconsistent states are distinct; non-entailment defaults require explicit task semantics. |
| Execution | Actual Tally, TELL, CaseLog, Warrant, Accrete and Finding rule APIs on the Mac; Tally arithmetic for sourced decimal/money expressions. |
| Review | One bounded model pass can revise a program using actual diagnostics/results. It distinguishes concrete defects from insufficient evidence. An uncertainty-only objection preserves a computed Unknown/NotMentioned result; actual defects still abstain. |
| Routing | Explicit rules/arithmetic/direct, or an inspectable heuristic based on source structure and declared numeric output. This is a runnable heuristic, not a trained/qualified router. |
| Evaluation | Direct once, direct plus review, and native program plus review on the same frozen inputs. Keys are read only by the separate scoring step. |
| Curriculum | Export requires exposed development data, valid program, native receipt, semantic review, matching target and explicit reviewer signoff on source/query/policy. It starts no training job. |

Run from the repository root with Python 3.10+; the package uses the standard library.

The included `reasoning-layer.ps1` launcher selects an installed Python interpreter and sets the package path for its invocation. The portable reference backend works without native engines or a model. The optional Mac bridge needs the separately installed fleet transport and original benchmark adapters. This is an experimental inspection/execution tool; the measured trials below did not show an overall answer-accuracy gain over direct review.

```powershell
# Validate supplied packets without a model or remote execution.
python -m reasoning_layer check reasoning_layer/example_data/packets.json --output checks.json

# Inspect whole-source accounting and the actual proof graph, locally.
python -m reasoning_layer audit reasoning_layer/example_data/audited-packets.json --output audit.json

# Execute the supplied rule and exact-money examples through the native Mac route.
python -m reasoning_layer execute reasoning_layer/example_data/packets.json --backend mac --output my-native-run

# Run a model writer plus one review, retaining all requests, programs and receipts.
python -m reasoning_layer run reasoning_layer/example_data/tasks.json --backend reference --output my-model-run

# A caller can explicitly select the local reference implementation for offline checks.
python -m reasoning_layer execute reasoning_layer/example_data/packets.json --backend reference --output my-reference-run

# Inspect deterministic routing; set a task's operation to auto to use the heuristic.
python -m reasoning_layer route reasoning_layer/example_data/tasks.json --output routes.json

# Matched three-condition evaluation; scoring is intentionally separate.
python -m reasoning_layer evaluate fresh_tasks.json --backend mac --output experiment-run

# Reconcile a completed remote native result after a transport interruption; never resubmits.
python -m reasoning_layer recover-native my-native-run/native --output recovered-state.json

# Resume a verified staging failure only when no execute command was ever launched.
python -m reasoning_layer resume-native interrupted-run/native --output staging-recovery.json

python -m unittest discover -s reasoning_layer/tests -v
```

`example_data/tasks.json` contains two complete task contracts. `example_data/packets.json` adds executable programs. An external AI can write this documented packet format and call `check`/`execute`; `model.PROGRAM` is its JSON Schema. The built-in `CodexModel` adapter uses the installed authenticated CLI, defaults to `gpt-6.1-sol` with high reasoning, disables tools/delegation/memory and saves raw requests/events. Hosted calls accept only explicitly declared public/synthetic tasks; private inputs retain their existing authorized Mac-only route.

`init` builds hashes, lexical query features and an explicit default policy from basic task records. The signature extractor is conservative lexical analysis. Callers with an authoritative domain annotation can supply its signature before freezing a task; it is never silently changed by the writer. Goal signatures and source quotes can still accompany a mistaken interpretation, so semantic review has its own recorded status and is not called a proof of source truth.

For binary tasks, decide whether the negative label means explicit refutation or non-entailment. Open-world absence produces Unknown/ABSTAIN. The SARA benchmark adapter uses its explicitly declared Prolog-negation-as-failure profile; that policy is not applied to other tasks. Conflicting support returns the caller's declared conflict state rather than silently selecting one side.

The optional native bridge uses the configured Windows fleet transport and separately installed benchmark adapters. Its current deployment defaults name the original local benchmark installation; users of the standalone package can use the reference backend immediately and provide their own backend adapter for other installations. Canonical language runtimes and ledgers remain unchanged. `state.json` pins a remote path before execution. A pending/failed call never causes automatic duplicate submission; `recover-native` fetches its existing result. `resume-native` permits completing a positively identified pre-execution staging failure under the same remote ID and refuses when an execute command may already have launched. Request/result hashes, compiled closure, engine consensus and unchanged runtime-entry hashes are checked. The `reference` backend is always labeled `native=false`.

Arithmetic accepts sourced bounded decimal operands and a small expression AST: names, numeric constants, parentheses and `+ - * /`. It rejects function calls, attributes, undeclared variables, unsupported units, zero division and money inputs beyond two decimal places. Formula intent and literal constants remain model proposals for review; operand span checks alone do not establish that the correct formula was chosen. The reference arithmetic phase uses 50-digit Decimal precision and the native result is cross-checked. Percentage/fraction normalization must be explicit in a future adapter rather than silently inferred by this one.

The model adapter is replaceable: implement `respond(prompt, schema, folder) -> dict`. The pipeline calls it once for writing and at most once for review. The supplied Codex adapter requires a locally authenticated Codex CLI. It disables tools and supplies only caller-declared public/synthetic tasks. Completed calls are reused against frozen inputs/settings; uncertain calls remain pinned. Preserve prompts, programs, checks, results and review decisions when comparing another adapter.

The retained 0.1 build trial scored 20/24 direct, 20/24 direct review and 18/24 through the layer. Its reviewer conflated insufficient evidence with a defective program. Version 0.2 distinguished those states; its separate focused cohort scored 10/12 direct, 10/12 direct review and 9/12 through the layer. All 12 final programs were valid and accepted by the reviewer, with zero native errors across 134 executions including both attempts. A missed contract permission still produced an incorrect NotMentioned result. These small trials include easy synthetic checks and establish no accuracy advantage. The public-only portions scored 8/12 versus 6/12, then 4/6 versus 3/6 on different cohorts. See [validation record](VALIDATION.md).

## Whole-source record

A source unit is an exact positional span with a source hash, character offsets and stable ID. Splitting preserves every non-whitespace character, including long paragraphs, tables flattened into text and repeated passages. Sentence boundaries are convenience boundaries; the full original context remains supplied to the model. Offset coverage can be checked mechanically. Whether an exception changes a claim remains a semantic judgment recorded for inspection.

Each program's `source_ledger` links represented units to `node:p1`, zero-based `rule:0`, `operand:fee_a` or `calculation:formula`. Quoted nodes/operands must overlap the linked unit. Every fact, supplied rule, operand and formula needs a source link; explicitly labeled External rules remain visible. Irrelevant units carry a question-specific reason. Unresolved representations retain a diagnostic and the underlying execution result. A complete ledger can still contain a mistaken judgment of irrelevance; it is never labeled proof of semantic completeness.

The default model pipeline requests this ledger in its first pass and checks the reviewer's unit-by-unit decisions against the final revised program in its second pass. An acceptance flag cannot bypass missing units or review decisions. The reviewer explicitly checks exceptions and conditions against the frozen query. The current conjunctive engine interface represents those only when they can be grounded faithfully; unresolved interpretations remain inspectable. Native engine agreement concerns execution of the supplied program, not agreement about the original prose.

Legacy packets remain executable and show `legacy_untracked` in the audit. Use `--legacy-source-review` only to replay the older review protocol; the mode is recorded and a cached run cannot silently change it. Source hashes bind reusable runs to the exact package recipe as well as inputs/settings, and a change during execution prevents a completion receipt. Existing 0.2 and 0.3.0 folders retain their original versions/settings. Choose a new output folder for upgraded runs. Reviewed curriculum exports from audited programs recheck the recorded source review before accepting a candidate. They start no training.

The release has 52 passing unit tests, three development diagnostics for prior failure mechanisms, and a current native smoke check of six rule engines plus Tally money arithmetic ($341.00). Historical scores and source snapshots remain preserved. The two build trials use different cohorts; their counts are not a before/after estimate of general improvement. The larger planned experiment protocols remain distinct from these bounded build trials. The earlier 42-question result remains in `../fresh-v2/` unchanged. Architecture proposals and exposure rules are indexed in `../architecture/`.

NARRATIVE GAUGE: 15% · plants 0 / payoffs 0 (all closed) · target 10–30%
