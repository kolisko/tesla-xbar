# Security

## Reporting a vulnerability

Use **Security → Report a vulnerability** on this GitHub repository. Do not put credentials, VINs, callback URLs, private keys or vehicle data in a public issue. Revoke exposed Tesla tokens and keys promptly if a leak occurs.

Security fixes target the latest release. This independent project is not affiliated with Tesla or xBar.

## Private profile

The public repository contains code, tests and fictional previews. Each user owns their Tesla Developer application, domain, signing key and credentials. There is no shared Tesla account, credential collection server or analytics.

- Client Secret and OAuth tokens stay in macOS Keychain.
- The private profile directory has mode 700; private data and signing keys use mode 600.
- Keys are created outside the checkout. Updates preserve existing profiles and never silently replace a missing key on an existing profile.
- The OAuth callback is temporary and loopback-only; it validates state and Host. Codes are not logged.
- Signed command tokens are passed through stdin. Raw helper errors are redacted.
- Normal refresh does not wake the car. Physical commands require explicit menu actions and a validated vehicle target.
- A local administrator or a process acting as the same macOS user may access local data. Filesystem permissions do not isolate malware running as the account owner.

## Repository checks

CI runs unit tests, a tracked-file privacy check, Gitleaks history scanning, macOS helper builds and a Go dependency vulnerability audit. CodeQL analyzes Python and Swift. Dependabot checks GitHub Actions updates. Workflow actions and the Tesla SDK revision are pinned; the SDK audit covers dependencies downloaded by its build.

GitHub secret scanning and push protection provide additional checks for supported secret patterns. These checks complement review; they cannot establish the absence of all vulnerabilities or personal information.

Tests and CI use fake accounts and temporary profiles. Never add real Tesla credentials to GitHub Actions secrets for this project. Do not use `pull_request_target` to execute contributor code with privileged tokens.
