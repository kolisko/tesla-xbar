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
dependency audit uses the same overlay.
