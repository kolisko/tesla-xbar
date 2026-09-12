#!/usr/bin/env python3
"""Tesla xBar entrypoint; dependency wiring lives in tesla_bar.bootstrap."""
if __package__ in (None, ""):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent / "tesla-runtime.zip"))
    from tesla_bar.bootstrap import main
else:
    from .tesla_bar.bootstrap import main

if __name__ == "__main__":
    raise SystemExit(main())
