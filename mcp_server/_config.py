"""MCP 工具服务的配置引导。

刻意从 backend 复用同一份 Settings，而不是在这里抄一遍端口/密钥：
- 端口、业务地址、JWT 密钥都是「改一处必须两处同步」的东西，
  复制一份迟早漂移（比如改了后端端口，MCP 还在回调旧地址）。
- 代价是需要在 sys.path 里加一行，值得。
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402

__all__ = ["settings", "BACKEND_DIR"]
