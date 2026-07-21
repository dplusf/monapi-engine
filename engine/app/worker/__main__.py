from __future__ import annotations

import asyncio

from app.worker.main import run


if __name__ == "__main__":
    asyncio.run(run())
