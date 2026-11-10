# Local source-linked program reasoning

Check and execute caller-supplied structured programs using the local reference
backend. Source spans, whole-source accounting, question identity, exact arithmetic
and derivation traces remain inspectable. This public distribution includes no
remote transport, hosted-model adapter or provider authentication.

```sh
python -m reasoning_layer check reasoning_layer/example_data/packets.json --output my-checks.json
python -m reasoning_layer execute reasoning_layer/example_data/packets.json --output my-local-run
python -m reasoning_layer audit reasoning_layer/example_data/audited-packets.json --output my-audit.json
```

The default and only bundled backend is `reference`; results identify local
reference execution rather than independent native-engine consensus. Use new
output directories. Packet schemas are in `schema/`; schema constants and payload
helpers remain in `model.py`. A caller may explicitly inject its own local
`respond(prompt, schema, folder)` implementation into the Python reasoning layer.
The compatibility names for old remote/provider adapters reject execution.

All bundled examples are synthetic. Generated packets, results and input files
belong outside Git. No fresh answer-accuracy claim follows from software tests.
