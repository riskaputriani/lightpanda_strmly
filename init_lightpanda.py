from __future__ import annotations

import sys
from pathlib import Path


def _bootstrap_src() -> None:
    src_dir = Path(__file__).parent / "src"
    src = str(src_dir)
    if src not in sys.path:
        sys.path.insert(0, src)


_bootstrap_src()

from lightpanda_local.init_lightpanda import main  # noqa: E402

raise SystemExit(main(sys.argv[1:]))
