"""
Flip Boost Price Manager Bot
Pure httpx long-polling — no telegram SDK needed
Works on Python 3.13+
"""
import os, asyncio, logging, httpx, json
from datetime import datetime
import pytz

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

BOT_TOKEN    = os.getenv("PRICE_BOT_TOKEN", "")
ADMIN_IDS    = [int(x) for x in os.getenv("ADMIN_CHAT_IDS", "775022253").split(",")]
FB_PROJECT   = os.getenv("FIREBASE_PROJECT", "flipboost-coffee")
FB_API_KEY   = os.getenv("FIREBASE_API_KEY", "")
ADD_TZ       = pytz.timezone("Africa/Addis_Ababa")

TG_API       = f"https://api.telegram.org/bot{BOT_TOKEN}"
FS_URL       = (f"https://firestore.googleapis.com/v1/projects/{FB_PROJECT}"
                f"/databases/(default)/documents/config/prices")

DEFAULT  = {"250g": 525, "500g": 1000, "1kg": 1900}
SIZE_KEY = {"250g": "price_250g", "500g": "price_500g", "1kg": "price_1kg"}

# ── Telegram helpers ──────────────────────────────────────
async def tg_send(client, chat_id, text):
    await client.post(f"{TG_API}/sendMessage",
                      json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"})

async def tg_get_updates(client, offset):
    r = await client.get(f"{TG_API}/getUpdates",
                         params={"offset": offset, "timeout": 30}, timeout=35)
    return r.json().get("result", [])

# ── Firestore helpers ─────────────────────────────────────
def _fs_url(extra=""):
    url = FS_URL + (f"?key={FB_API_KEY}" if FB_API_KEY else "")
    return url + extra

async def get_prices(client):
    try:
        r = await client.get(_fs_url(), timeout=8)
        if r.status_code == 200:
            f = r.json().get("fields", {})
            def v(field, default):
                d = f.get(field, {})
                return int(d.get("integerValue") or d.get("stringValue") or default)
            return {"250g": v("price_250g", 525),
                    "500g": v("price_500g", 1000),
                    "1kg":  v("price_1kg",  1900)}
    except Exception as e:
        log.error(f"get_prices: {e}")
    return DEFAULT.copy()

async def set_price(client, size, price, admin_name):
    fkey = SIZE_KEY[size]
    now  = datetime.now(ADD_TZ).strftime("%Y-%m-%d %H:%M:%S EAT")
    payload = {"fields": {
        fkey:         {"stringValue": str(price)},
        "updated_by": {"stringValue": admin_name},
        "updated_at": {"stringValue": now},
    }}
    sep  = "&" if FB_API_KEY else "?"
    mask = (f"{sep}updateMask.fieldPaths={fkey}"
            f"&updateMask.fieldPaths=updated_by"
            f"&updateMask.fieldPaths=updated_at")
    try:
        r = await client.patch(_fs_url() + mask, json=payload, timeout=8)
        if r.status_code in (200, 201):
            return True, f"✅ ዋጋ ተቀይሯል\!\n📦 {size.upper()} → ETB {price:,}\n🕐 {now}"
        return False, f"❌ Firestore error {r.status_code}: {r.text[:200]}"
    except Exception as e:
        return False, f"❌ Network error: {e}"

# ── Command handlers ──────────────────────────────────────
async def handle_message(client, msg):
    chat_id = msg["chat"]["id"]
    user_id = msg["from"]["id"]
    text    = msg.get("text", "").strip()

    if user_id not in ADMIN_IDS:
        return

    if text == "/start":
        await tg_send(client, chat_id,
            "☕ *Flip Boost Price Bot*\n\n"
            "Commands:\n"
            "`/setprice 250g 600`\n"
            "`/setprice 500g 1100`\n"
            "`/setprice 1kg 2000`\n"
            "`/prices` — አሁን ያሉ ዋጋዎች")

    elif text == "/prices":
        p = await get_prices(client)
        await tg_send(client, chat_id,
            f"☕ *አሁን ያሉ ዋጋዎች*\n\n"
            f"  250g → ETB {p['250g']:,}\n"
            f"  500g → ETB {p['500g']:,}\n"
            f"  1kg  → ETB {p['1kg']:,}\n\n"
            f"_Site ቀጣይ ጊዜ ሲጫን ይዘምናል_")

    elif text.startswith("/setprice"):
        parts = text.split()
        if len(parts) != 3:
            await tg_send(client, chat_id,
                "📌 Usage:\n`/setprice 250g 600`\n`/setprice 500g 1100`\n`/setprice 1kg 2000`")
            return
        size = parts[1].lower().replace(" ", "")
        if size not in SIZE_KEY:
            await tg_send(client, chat_id, "❌ Size 250g, 500g ወይም 1kg መሆን አለበት።")
            return
        try:
            price = int(parts[2].replace(",", ""))
        except ValueError:
            await tg_send(client, chat_id, "❌ ዋጋ ቁጥር መሆን አለበት።")
            return
        if not (1 <= price <= 100000):
            await tg_send(client, chat_id, "❌ ዋጋ ከ 1 እስከ 100,000 ETB መሆን አለበት።")
            return
        admin_name = msg["from"].get("first_name", "admin")
        ok, reply = await set_price(client, size, price, admin_name)
        await tg_send(client, chat_id, reply)

# ── Main polling loop ─────────────────────────────────────
async def main():
    if not BOT_TOKEN:
        raise ValueError("PRICE_BOT_TOKEN not set!")
    log.info("🚀 Flip Boost Price Bot started!")
    offset = 0
    async with httpx.AsyncClient() as client:
        while True:
            try:
                updates = await tg_get_updates(client, offset)
                for update in updates:
                    offset = update["update_id"] + 1
                    if "message" in update:
                        await handle_message(client, update["message"])
            except Exception as e:
                log.error(f"Polling error: {e}")
                await asyncio.sleep(3)

if __name__ == "__main__":
    asyncio.run(main())
