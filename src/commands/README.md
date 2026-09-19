# Command helper adapter

`climate.go` adds the `climate-keeper off|on|dog|camp` CLI command to the pinned
Tesla command helper. It calls the SDK's existing `SetClimateKeeperMode` method
with manual override disabled. Signing, credentials, sessions and transport stay
in Tesla's SDK. Normal climate on/off and temperature commands already exist there.

`climate_test.go` checks mode mapping, authentication and rejection of invalid
arguments without contacting a vehicle.

[`scripts/build_commands.py`](../../scripts/build_commands.py) uses Go's build
overlay to add these files to the CLI package without modifying the verified SDK
checkout. It runs the adapter tests and builds `build/tesla-control`. The generated
`build/command-overlay.json` contains local paths and is never committed. The
dependency audit materializes the same adapter in a temporary copy of the SDK
because govulncheck's source parser does not support virtual overlay files.

`diagnostics.go` observes `httptrace.WroteRequest` in the SDK transport and records
only the two latest successful request-write times in the private diagnostics
file shared with Python. This includes session negotiation and error responses;
it does not log tokens, URLs, VINs or payloads, and does not issue any requests.
`diagnostics_test.go` uses a fake transport to verify dispatch-only recording and
private, bounded storage. The hook is enabled only for the plugin's subprocess
through its private profile path.
