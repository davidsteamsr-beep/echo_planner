"""Запуск: из папки bot → python run_local.py
или из родителя → python -m bot
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import asyncio
from bot.main import main

if __name__ == "__main__":
    asyncio.run(main())
