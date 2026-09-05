import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
load_dotenv(ROOT.parent / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN") or "8973557526:AAFy1neG6ZKvXyKwtt0Ek2zElxgPvZpxXG0"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY") or os.getenv("AITUNNEL_KEY") or "sk-aitunnel-A0PIkMCeZbhFW65hWXmis7UF1dIPwt21"
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.aitunnel.ru/v1")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or 0)
WEBAPP_URL = os.getenv("WEBAPP_URL") or os.getenv("MINI_APP_URL") or ""

# Telegram Payments provider token (BotFather → Payments → ЮKassa)
PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN", "")

# YooKassa direct (optional)
YOOKASSA_SHOP_ID = os.getenv("YOOKASSA_SHOP_ID", "")
YOOKASSA_SECRET_KEY = os.getenv("YOOKASSA_SECRET_KEY", "")

DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
ASSETS_DIR = ROOT / "assets"

# Тарифы (копейки)
PRICE_MONTHLY = 25000   # 250 ₽
PRICE_LIFETIME = 299000  # 2990 ₽
CURRENCY = "RUB"
TRIAL_DAYS = 5
