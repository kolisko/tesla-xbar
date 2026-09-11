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

Swift scanning uses a fixed Xcode 16.4 toolchain on an Intel macOS runner, while the ordinary build tests the latest Apple Silicon runner. CodeQL 2.26.4 has an [upstream performance issue in lazy declaration extraction](https://github.com/github/codeql/pull/22408). The Swift build is allowed up to 30 minutes and the job up to 40 minutes; analysis remains required and findings are not suppressed. Superseded runs are cancelled automatically.

GitHub secret scanning and push protection provide additional checks for supported secret patterns. These checks complement review; they cannot establish the absence of all vulnerabilities or personal information.

Tests and CI use fake accounts and temporary profiles. Never add real Tesla credentials to GitHub Actions secrets for this project. Do not use `pull_request_target` to execute contributor code with privileged tokens.

Optional Location access saves only the latest coordinates, address and timestamps in the private profile. Apple receives coordinates for reverse geocoding and map opening; it never receives Tesla credentials or VIN. Location is disabled by default. Disabling it clears location from the cache and display snapshot. Do not post either file in issues. The `tesla-location` Swift helper is included in CodeQL and macOS builds.

The map preview requires a separate `location_map_enabled` opt-in. MapMap receives a viewport centered on the saved vehicle position, revealing that position, but no VIN, address, tokens or account data. The request does not follow redirects, bounds response size/dimensions and times out. `tesla-map-image` receives image bytes only and draws the marker locally; it is included in CodeQL/macOS builds. A checksum and vehicle/position identity guard against showing a different or corrupted cached map. The PNG and menu snapshot reveal location and must stay private. Disabling Location or the preview deletes the PNG. Map failures do not cause vehicle commands or extra Tesla calls.
