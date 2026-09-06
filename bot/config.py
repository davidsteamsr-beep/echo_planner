import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
load_dotenv(ROOT.parent / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN") or ""
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY") or os.getenv("AITUNNEL_KEY") or ""
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.aitunnel.ru/v1")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or 0)

WEBAPP_URL = os.getenv("WEBAPP_URL") or os.getenv("MINI_APP_URL") or "https://davidsteamsr-beep.github.io/echo_planner/"
BOT_USERNAME = os.getenv("BOT_USERNAME", "Echo_Planner_bot")
API_PUBLIC_URL = os.getenv("API_PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL") or "https://echo-planner-ppeb.onrender.com"

PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN", "")
YOOKASSA_SHOP_ID = os.getenv("YOOKASSA_SHOP_ID", "")
YOOKASSA_SECRET_KEY = os.getenv("YOOKASSA_SECRET_KEY", "")

DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
ASSETS_DIR = ROOT / "assets"

PRICE_MONTHLY = 25000   # 250 ₽
PRICE_LIFETIME = 299000  # 2990 ₽
CURRENCY = "RUB"
TRIAL_DAYS = 5

WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
