import os, asyncio, json, httpx
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import anthropic
print("BOT KHOI DONG", flush=True)
TOKEN = os.environ["BOT_TOKEN"]
GROUP_ID = int(os.environ["GROUP_ID"])
ANTHROPIC_KEY = os.environ["ANTHROPIC_KEY"]

entries = []
client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
BASE = f"https://api.telegram.org/bot{TOKEN}"

CLASSIFY_PROMPT = """Bạn là trợ lý nhật ký bán hàng Galaxy Golf Nha Trang.
Phân tích tin nhắn tự do và xác định loại giao dịch.
Trả về JSON, KHÔNG có markdown:
{
  "loai": "BÁN" hoặc "NHẬP" hoặc "THU CHI" hoặc "KHÔNG RÕ",
  "du_lieu": {
    "kh": "tên khách",
    "sdt": "số điện thoại",
    "dia_chi": "địa chỉ giao hàng",
    "sp": "tên sản phẩm",
    "gia": "số tiền nguyên",
    "tt": "TM/CK/COD/Ký gửi",
    "ncc": "nhà cung cấp nếu NHẬP",
    "gc": "ghi chú"
  },
  "thieu": ["trường còn thiếu quan trọng"]
}"""

REPORT_PROMPT = """Tạo báo cáo cuối ngày Galaxy Golf Nha Trang từ dữ liệu giao dịch.
Format:
📅 NHẬT KÝ BÁN HÀNG — [NGÀY]
🏪 Galaxy Golf Nha Trang

🛒 BÁN HÀNG: X đơn
[chi tiết]
→ Tổng: X đ

📦 NHẬP HÀNG: X lô
[chi tiết]
→ Tổng: X đ

💰 THU CHI KHÁC:
[chi tiết]

📊 TỔNG KẾT:
Doanh thu: X đ
Tiền nhập: X đ
Thu khác: X đ
Chi khác: X đ
LỢI NHUẬN GỘP: X đ"""

async def send_message(chat_id, text, reply_to=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_to:
        payload["reply_to_message_id"] = reply_to
    async with httpx.AsyncClient() as http:
        await http.post(f"{BASE}/sendMessage", json=payload)

async def process_message(msg):
    text = msg.get("text", "").strip()
    if len(text) < 5:
        return
    user = msg.get("from", {}).get("first_name", "NV")
    msg_id = msg.get("message_id")
    chat_id = msg.get("chat", {}).get("id")

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            system=CLASSIFY_PROMPT,
            messages=[{"role": "user", "content": text}]
        )
        data = json.loads(response.content[0].text.strip())
        print(f"Claude OK: {data}", flush=True)
    except Exception as e:
        print(f"Claude error: {e}", flush=True)
        return

    loai = data.get("loai", "KHÔNG RÕ")
    if loai == "KHÔNG RÕ":
        return

    du_lieu = data.get("du_lieu", {})
    thieu = data.get("thieu", [])

    entries.append({
        "time": datetime.now().strftime("%H:%M"),
        "user": user,
        "loai": loai,
        "du_lieu": du_lieu,
        "raw": text
    })

    gia = du_lieu.get("gia", "")
    try:
        gia_fmt = f"{int(gia):,}đ".replace(",", ".")
    except:
        gia_fmt = gia

    if loai == "BÁN":
        reply = f"✅ Ghi nhận bán *{du_lieu.get('sp','')}*"
        if du_lieu.get('kh'): reply += f" cho {du_lieu.get('kh')}"
        if gia_fmt: reply += f" — {gia_fmt}"
        if du_lieu.get('tt'): reply += f" ({du_lieu.get('tt')})"
        if du_lieu.get('dia_chi'): reply += f"\n📍 {du_lieu.get('dia_chi')}"
    elif loai == "NHẬP":
        reply = f"📦 Ghi nhận nhập *{du_lieu.get('sp','')}*"
        if gia_fmt: reply += f" — {gia_fmt}"
    else:
        reply = f"💰 Ghi nhận {du_lieu.get('gc','')}"
        if gia_fmt: reply += f" — {gia_fmt}"

    if thieu:
        reply += f"\n⚠️ Còn thiếu: {', '.join(thieu)}"

    await send_message(chat_id, reply, reply_to=msg_id)

async def send_daily_report():
    ngay = datetime.now().strftime("%d/%m/%Y")
    if not entries:
        await send_message(GROUP_ID, f"📊 Ngày {ngay}: Chưa có giao dịch nào.")
        return

    all_entries = "\n\n".join([
        f"[{e['time']} - {e['user']} - {e['loai']}]\n{e['raw']}"
        for e in entries
    ])

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        system=REPORT_PROMPT,
        messages=[{"role": "user", "content": f"Ngày {ngay}:\n\n{all_entries}"}]
    )

    await send_message(GROUP_ID, f"📊 *BÁO CÁO CUỐI NGÀY*\n\n{response.content[0].text}")
    entries.clear()

async def polling():
    offset = 0
    print("Bot started, polling...")
    async with httpx.AsyncClient(timeout=35) as http:
        while True:
            try:
                r = await http.get(f"{BASE}/getUpdates", params={"offset": offset, "timeout": 30})
                updates = r.json().get("result", [])
                for u in updates:
                    offset = u["update_id"] + 1
                    msg = u.get("message")
                    print(f"Received update: {u}")
                    if msg and msg.get("text"):
                        asyncio.create_task(process_message(msg))
            except Exception as e:
                print(f"Polling error: {e}")
                await asyncio.sleep(5)

async def main():
    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_daily_report, "cron", hour=20, minute=0)
    scheduler.start()
    await polling()

if __name__ == "__main__":
    asyncio.run(main())
