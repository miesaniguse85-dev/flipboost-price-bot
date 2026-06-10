"""
Flip Boost Price Manager Bot
Railway standalone service — /setprice command
"""

import os, requests, logging
from datetime import datetime
import pytz
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)

# ── Config ──────────────────────────────────────────────
BOT_TOKEN    = os.getenv("PRICE_BOT_TOKEN", "")
ADMIN_IDS    = [int(x) for x in os.getenv("ADMIN_CHAT_IDS", "775022253").split(",")]
FB_PROJECT   = os.getenv("FIREBASE_PROJECT", "flipboost-coffee")
FB_API_KEY   = os.getenv("FIREBASE_API_KEY", "")   # optional Web API key
ADD_TZ       = pytz.timezone("Africa/Addis_Ababa")

FIRESTORE_URL = (
    f"https://firestore.googleapis.com/v1/projects/{FB_PROJECT}"
    f"/databases/(default)/documents/config/prices"
)

DEFAULT = {"250g": 525, "500g": 1000, "1kg": 1900}
SIZE_KEY = {"250g": "price_250g", "500g": "price_500g", "1kg": "price_1kg"}

# ── Firestore helpers ────────────────────────────────────
def _url(extra=""):
    base = FIRESTORE_URL
    sep  = "?" if not extra.startswith("&") else ""
    if FB_API_KEY:
        base += f"?key={FB_API_KEY}"
        sep = "&"
    return base + sep + extra

def get_prices():
    try:
        r = requests.get(_url(), timeout=8)
        if r.status_code == 200:
            f = r.json().get("fields", {})
            return {
                "250g": int(f.get("price_250g", {}).get("integerValue") or f.get("price_250g", {}).get("stringValue") or DEFAULT["250g"]),
                "500g": int(f.get("price_500g", {}).get("integerValue") or f.get("price_500g", {}).get("stringValue") or DEFAULT["500g"]),
                "1kg":  int(f.get("price_1kg",  {}).get("integerValue") or f.get("price_1kg",  {}).get("stringValue") or DEFAULT["1kg"]),
            }
    except Exception as e:
        logging.error(f"get_prices: {e}")
    return DEFAULT.copy()

def set_price(size, price, admin_name):
    fkey = SIZE_KEY[size]
    now  = datetime.now(ADD_TZ).strftime("%Y-%m-%d %H:%M:%S EAT")
    payload = {
        "fields": {
            fkey:          {"stringValue": str(price)},
            "updated_by":  {"stringValue": admin_name},
            "updated_at":  {"stringValue": now},
        }
    }
    mask = (
        f"updateMask.fieldPaths={fkey}"
        f"&updateMask.fieldPaths=updated_by"
        f"&updateMask.fieldPaths=updated_at"
    )
    try:
        sep = "&" if FB_API_KEY else "?"
        r = requests.patch(_url() + sep + mask, json=payload, timeout=8)
        if r.status_code in (200, 201):
            return True, f"✅ ዋጋ ተቀይሯል!\n📦 {size.upper()} → ETB {price:,}\n🕐 {now}"
        return False, f"❌ Firestore error {r.status_code}: {r.text[:200]}"
    except Exception as e:
        return False, f"❌ Network error: {e}"

# ── Bot handlers ─────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    await update.message.reply_text(
        "☕ *Flip Boost Price Bot*\n\n"
        "Commands:\n"
        "`/setprice 250g 600`\n"
        "`/setprice 500g 1100`\n"
        "`/setprice 1kg 2000`\n"
        "`/prices` — አሁን ያሉ ዋጋዎች",
        parse_mode="Markdown"
    )

async def cmd_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    p = get_prices()
    await update.message.reply_text(
        f"☕ *አሁን ያሉ ዋጋዎች*\n\n"
        f"  250g → ETB {p['250g']:,}\n"
        f"  500g → ETB {p['500g']:,}\n"
        f"  1kg  → ETB {p['1kg']:,}\n\n"
        f"_Site ቀጣይ ጊዜ ሲጫን ይዘምናል_",
        parse_mode="Markdown"
    )

async def cmd_setprice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Unauthorized.")
        return

    args = context.args
    if len(args) != 2:
        await update.message.reply_text(
            "📌 Usage:\n`/setprice 250g 600`\n`/setprice 500g 1100`\n`/setprice 1kg 2000`",
            parse_mode="Markdown"
        )
        return

    size = args[0].lower().replace(" ", "")
    if size not in SIZE_KEY:
        await update.message.reply_text("❌ Size 250g, 500g ወይም 1kg መሆን አለበት።")
        return

    try:
        price = int(args[1].replace(",", ""))
    except ValueError:
        await update.message.reply_text("❌ ዋጋ ቁጥር መሆን አለበት። ለምሳሌ: `/setprice 250g 600`", parse_mode="Markdown")
        return

    if not (1 <= price <= 100000):
        await update.message.reply_text("❌ ዋጋ ከ 1 እስከ 100,000 ETB መሆን አለበት።")
        return

    admin_name = update.effective_user.full_name or "admin"
    success, msg = set_price(size, price, admin_name)
    await update.message.reply_text(msg, parse_mode="Markdown")

# ── Main ─────────────────────────────────────────────────
def main():
    token = BOT_TOKEN
    if not token:
        raise ValueError("PRICE_BOT_TOKEN environment variable not set!")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("prices",   cmd_prices))
    app.add_handler(CommandHandler("setprice", cmd_setprice))

    logging.info("🚀 Flip Boost Price Bot started!")
    app.run_polling(allowed_updates=["message"])

if __name__ == "__main__":
    main()
