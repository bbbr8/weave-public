# Weave

Weave validates and runs structured analytical plans across Loom, Tally, OLAP and QULAP adapters. It checks dependencies, source lineage, exact results and hash-bound execution receipts.

## Quick start

Use Python 3.10 or newer. The core and portable tests use the standard library.

```sh
python weave.py example.json
python weave_registry.py --summary
python -m unittest discover -v
python weave_demo.py outputs/demo
```

The demo creates synthetic records, verifies their results and demonstrates rejection of an altered result. Choose a new output directory for each run.

## Runtime configuration

Native engines are separate installations. Supply their paths with `--runtime` to the adapter CLIs; run an adapter with `--help` for its schema and arguments. No engine is marked available in the default catalog. Configure your own local copy with `WEAVE_CATALOG`, or pass `--catalog` to the verifier. Runtime and registered-program hashes are checked when loading that catalog.

- `weave_tally.py`: bounded exact integer arithmetic.
- `weave_infer.py`: sourced rule inference.
- `weave_qulap.py`: finite alternatives and completion policies.
- `weave_loom.py`: search and record reading.
- `weave_olap.py`: bounded integer aggregation.
- `weave_run.py`: typed bindings and combined execution receipts.
- `weave_verify.py`: plan readiness and result assertions.
- `weave_select.py`: verify candidate bundles under one request, group declared
  observations, and request a distinguishing check when verified outcomes disagree.

This standalone distribution includes synthetic tests and a local catalog loader. Native adapter execution requires compatible external runtimes and is separate from portable test validation. No model weights are included.

## Compare model-generated alternatives

`python weave_refine.py --demo` runs a complete synthetic refinement loop. A
source-bound expected value resolves an ambiguous pool and the updated request
is verified again; repeated wrong candidates cannot gain voting weight.

The Python `weave_refine.refine` API accepts an explicit oracle callback and an
optional proposer callback. Proposers supply executed candidate bundles; the
refinement loop calls no provider and executes no generated code implicitly.
It retains request revisions, source-bound oracle records and all diagnostics.
Round/candidate exhaustion, missing oracles, failed candidates and convergence
under supplied checks have distinct states. `python weave_refine.py packet.json`
supports offline `oracle_answers` matched by result step and pointer. Each answer
has `value`, `basis`, and `sources` containing declared `{id, sha256}` bindings.

`python weave_select.py packet.json` reads a packet containing `request`, `catalog`,
`candidates` and `observations`. A candidate has `id`, a relative `directory` below
the packet folder, and its `receipts`. An observation has a result `step` and JSON
`pointer`. Supply 1–32 candidates and 1–32 observations.

The existing verifier checks every candidate before comparison. Identical declared
outcomes form one class regardless of copy count. Conflicting classes return
`DISAGREEMENT` and a next observation minimizing the largest remaining class count;
obtain its expected value independently and add a request assertion. Agreement is
limited to the supplied checks and projections. This command calls no model, runs
no generated code and provides no execution attestation. Its exit status is zero
for agreement under checks, one for disagreement/rejection and two for bad input.

Keep real records, credentials, runtime configuration and generated outputs outside Git. This repository starts with a fresh source snapshot.


## Source-linked model reasoning

The optional [reasoning layer](reasoning_layer/README.md) adds whole-source accounting, explicit query/answer policies, exact calculations and inspectable derivation records around model-written programs. Run `python -m reasoning_layer audit reasoning_layer/example_data/audited-packets.json --output outputs/reasoning/audit.json` for a portable synthetic example. The reference backend uses the standard library; external runtimes are optional separate local installations. The distributed reasoning layer uses its local reference backend. The [validation record](reasoning_layer/VALIDATION.md) distinguishes software checks, development diagnostics and answer accuracy.

## Evaluation hardening

Refinement freezes the request, catalog and observation list before callbacks and records their hashes. Oracles must preserve observed units; mixed units require an explicit oracle unit. Exhausting the 128-check budget returns `CHECK_BUDGET_EXHAUSTED` before calling an oracle. Duplicate proposed IDs are rejected before re-verification. Candidate code remains externally executed; callback assertions remain caller supplied.

## Local-only distribution

No HTTP service, hosted-model adapter, remote-machine bridge or deployment
configuration is included. Use the CLI or local Python modules. See
[PUBLIC_DISTRIBUTION.md](PUBLIC_DISTRIBUTION.md).
