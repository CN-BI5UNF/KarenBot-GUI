"""由启动器调用的真实 GUI 入口；不要从这里再进入 launcher。"""

from __future__ import annotations

from .app import main

raise SystemExit(main())
