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

This standalone distribution includes synthetic tests and a local catalog loader. Native adapter execution requires compatible external runtimes and is separate from portable test validation. No model weights are included.

Keep real records, credentials, runtime configuration and generated outputs outside Git. This repository starts with a fresh source snapshot.


## Source-linked model reasoning

The optional [reasoning layer](reasoning_layer/README.md) adds whole-source accounting, explicit query/answer policies, exact calculations and inspectable derivation records around model-written programs. Run `python -m reasoning_layer audit reasoning_layer/example_data/audited-packets.json --output outputs/reasoning/audit.json` for a portable synthetic example. The reference backend uses the standard library; native engines and the Codex model adapter require separate local installations. The [validation record](reasoning_layer/VALIDATION.md) distinguishes software checks, development diagnostics and answer accuracy.
