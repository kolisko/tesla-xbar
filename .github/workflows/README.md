# GitHub Actions workflows

| Workflow | Checks |
| --- | --- |
| [`ci.yml`](ci.yml) | Unit tests, tracked-file privacy scan, Gitleaks history scan, macOS helper builds and a Go dependency vulnerability audit. |
| [`codeql.yml`](codeql.yml) | Python and Swift analysis with security-extended queries. Swift uses an explicit helper build and a fixed analysis toolchain. |

Both workflows run for pull requests and pushes to `main`, with additional scheduled and manual runs. Superseded runs are cancelled automatically. Action dependencies are pinned to commit SHAs.

Commands execute from the repository root. Application sources are in [`src/`](../../src/README.md), tools in [`scripts/`](../../scripts/README.md), and tests in [`tests/`](../../tests/README.md). Build output goes into the ignored `build/` directory.

The helper build runs the climate adapter's Go tests. The Go vulnerability audit
uses a temporary SDK copy with the same adapter materialized as ordinary files,
so its source parser analyzes the complete CLI package built for installation.

The [security policy](../SECURITY.md) describes the checks and Swift analysis timing. Workflows use fake accounts and must not receive real Tesla credentials.
