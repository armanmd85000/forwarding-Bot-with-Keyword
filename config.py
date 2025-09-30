import os

# ✅ Telegram API credentials
# Get these from https://my.telegram.org -> API Development Tools
API_ID = int(os.environ.get("API_ID", "0"))         # must be an integer
API_HASH = os.environ.get("API_HASH", "")

# ✅ Bot token from @BotFather
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# --- Optional: local fallback (only for testing on your PC) ---
# If environment variables are not set, you can hardcode here:
# API_ID = 123456
# API_HASH = "abcdef1234567890abcdef1234567890"
# BOT_TOKEN = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
