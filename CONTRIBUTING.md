# Contributing

Open an issue or pull request with a focused change and its user-visible behavior. Run:

```sh
python3 -B -m unittest test_tesla_xbar test_commands test_reliability test_install
python3 scripts/check_public_files.py
```

Tests use temporary profiles and fake Tesla clients. Do not add real credentials or send real vehicle commands in tests. Keep normal refresh separate from explicit physical actions. Preserve saved readings, private profiles and vehicle selection when updating.

Use pull requests for changes to `main`; required checks must pass. GitHub Actions are pinned to commit SHAs. The official Tesla SDK revision is pinned in `build_commands.py`; a version update must include review of upstream changes and a passing Go vulnerability audit. Dependabot updates workflow actions, not the SDK's embedded revision.

`scripts/render_previews.py` generates SVG illustrations from fictional data. PNGs are rendered from those SVGs for README compatibility. Never use an unredacted desktop screenshot as a documentation asset. The original prototypes and private operational notes are intentionally excluded from this repository.

Report vulnerabilities through the private reporting link described in [SECURITY.md](SECURITY.md).
