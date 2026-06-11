import os, asyncio, logging, httpx
from datetime import datetime
import pytz

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

BOT_TOKEN  = os.getenv("PRICE_BOT_TOKEN", "")
ADMIN_IDS  = [int(x) for x in os.getenv("ADMIN_CHAT_IDS", "775022253").split(",")]
FB_PROJECT = os.getenv("FIREBASE_PROJECT", "flipboost-coffee")
ADD_TZ     = pytz.timezone("Africa/Addis_Ababa")

TG_API  = f"https://api.telegram.org/bot{BOT_TOKEN}"
FS_URL  = (f"https://firestore.googleapis.com/v1/projects/{FB_PROJECT}"
           f"/databases/(default)/documents/config/prices")

SIZE_KEY = {"250g": "price_250g", "500g": "price_500g", "1kg": "price_1kg"}

async def send(client, chat_id, text):
    r = await client.post(f"{TG_API}/sendMessage",
                      json={"chat_id": chat_id, "text": text},
                      timeout=10)
    log.info(f"sendMessage to {chat_id}: {r.status_code}")

async def get_updates(client, offset):
    r = await client.get(f"{TG_API}/getUpdates",
                         params={"offset": offset, "timeout": 30},
                         timeout=35)
    return r.json().get("result", [])

async def get_prices(client):
    try:
        r = await client.get(FS_URL, timeout=8)
        if r.status_code == 200:
            f = r.json().get("fields", {})
            def v(k, d):
                x = f.get(k, {})
                return int(x.get("integerValue") or x.get("stringValue") or d)
            return {"250g": v("price_250g", 525),
                    "500g": v("price_500g", 1000),
                    "1kg":  v("price_1kg",  1900)}
    except Exception as e:
        log.error(f"get_prices: {e}")
    return {"250g": 525, "500g": 1000, "1kg": 1900}

async def set_price(client, size, price, admin_name):
    fkey = SIZE_KEY[size]
    now  = datetime.now(ADD_TZ).strftime("%Y-%m-%d %H:%M:%S EAT")
    payload = {"fields": {
        fkey:         {"stringValue": str(price)},
        "updated_by": {"stringValue": admin_name},
        "updated_at": {"stringValue": now},
    }}
    mask = (f"?updateMask.fieldPaths={fkey}"
            f"&updateMask.fieldPaths=updated_by"
            f"&updateMask.fieldPaths=updated_at")
    try:
        r = await client.patch(FS_URL + mask, json=payload, timeout=8)
        if r.status_code in (200, 201):
            return True, f"OK {size.upper()} ETB {price:,} at {now}"
        return False, f"Firestore error {r.status_code}"
    except Exception as e:
        return False, f"Network error: {e}"

async def handle(client, msg):
    chat_id = msg["chat"]["id"]
    user_id = msg["from"]["id"]
    text    = msg.get("text", "").strip()

    log.info(f"MSG from user_id={user_id} chat_id={chat_id}: {text[:50]}")

    if user_id not in ADMIN_IDS:
        log.warning(f"Unauthorized: {user_id}")
        return

    if text in ("/start", "/help"):
        await send(client, chat_id,
            "Flip Boost Price Bot\n\n"
            "/setprice 250g 600\n"
            "/setprice 500g 1100\n"
            "/setprice 1kg 2000\n"
            "/setall 525 1000 1900\n"
            "/prices")

    elif text == "/prices":
        p = await get_prices(client)
        await send(client, chat_id,
            f"Prices:\n250g={p['250g']}\n500g={p['500g']}\n1kg={p['1kg']}")

    elif text.startswith("/setall"):
        parts = text.split()
        log.info(f"setall parts={parts}")
        if len(parts) != 4:
            await send(client, chat_id, "Usage: /setall 525 1000 1900")
            return
        sizes  = ["250g", "500g", "1kg"]
        admin  = msg["from"].get("first_name", "admin")
        lines  = []
        for i, size in enumerate(sizes):
            try:
                price = int(parts[i+1].replace(",",""))
            except:
                lines.append(f"ERR {size}")
                continue
            ok, reply = await set_price(client, size, price, admin)
            lines.append(reply)
        await send(client, chat_id, "\n".join(lines))

    elif text.startswith("/setprice"):
        parts = text.split()
        if len(parts) != 3:
            await send(client, chat_id, "Usage: /setprice 250g 600")
            return
        size = parts[1].lower()
        if size not in SIZE_KEY:
            await send(client, chat_id, "Size: 250g, 500g, 1kg")
            return
        try:
            price = int(parts[2].replace(",",""))
        except:
            await send(client, chat_id, "Price must be a number")
            return
        admin = msg["from"].get("first_name", "admin")
        ok, reply = await set_price(client, size, price, admin)
        await send(client, chat_id, reply)

async def main():
    if not BOT_TOKEN:
        raise ValueError("PRICE_BOT_TOKEN not set!")
    log.info(f"Bot started! ADMIN_IDS={ADMIN_IDS}")
    offset = 0
    async with httpx.AsyncClient() as client:
        while True:
            try:
                updates = await get_updates(client, offset)
                for u in updates:
                    offset = u["update_id"] + 1
                    if "message" in u:
                        await handle(client, u["message"])
            except Exception as e:
                log.error(f"Polling error: {e}")
                await asyncio.sleep(3)

if __name__ == "__main__":
    asyncio.run(main())
