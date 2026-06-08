import os, asyncio, json
from datetime import datetime
from telegram import Update, Bot
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
import anthropic

TOKEN = os.environ["BOT_TOKEN"]
GROUP_ID = int(os.environ["GROUP_ID"])
ANTHROPIC_KEY = os.environ["ANTHROPIC_KEY"]

entries = []
client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

CLASSIFY_PROMPT = """Bạn là trợ lý nhật ký bán hàng Galaxy Golf Nha Trang.

Nhiệm vụ: Phân tích tin nhắn tự do từ nhân viên và xác định đây là giao dịch gì.

Quy tắc phân loại:
- BÁN: có thông tin bán hàng cho khách (tên khách, sản phẩm, giá)
- NHẬP: hàng về kho, nhập từ nhà cung cấp
- THU CHI: thu tiền hoặc chi tiền vận hành
- KHÔNG RÕ: tin nhắn không liên quan đến giao dịch

Trả về JSON theo format sau, KHÔNG có markdown:
{
  "loai": "BÁN" hoặc "NHẬP" hoặc "THU CHI" hoặc "KHÔNG RÕ",
  "du_lieu": {
    "kh": "tên khách (nếu có)",
    "sdt": "số điện thoại (nếu có)",
    "dia_chi": "địa chỉ giao hàng (nếu có)",
    "sp": "tên sản phẩm",
    "gia": "số tiền (chỉ số nguyên)",
    "tt": "hình thức thanh toán: TM/CK/COD/Ký gửi",
    "ncc": "nhà cung cấp (nếu là NHẬP)",
    "gc": "ghi chú thêm"
  },
  "thieu": ["danh sách trường còn thiếu quan trọng"],
  "xac_nhan": "tin nhắn xác nhận ngắn gọn cho nhân viên"
}"""

REPORT_PROMPT = """Bạn là trợ lý tổng hợp nhật ký bán hàng Galaxy Golf Nha Trang.
Từ danh sách giao dịch trong ngày, tạo báo cáo cuối ngày theo format:

📅 NHẬT KÝ BÁN HÀNG — [NGÀY]
🏪 Galaxy Golf Nha Trang

🛒 BÁN HÀNG: [số đơn] đơn
[liệt kê từng đơn]
→ Tổng doanh thu: [số tiền]

📦 NHẬP HÀNG: [số lô] lô  
[liệt kê]
→ Tổng tiền nhập: [số tiền]

💰 THU CHI KHÁC:
[liệt kê]

📊 TỔNG KẾT:
Doanh thu bán: [số]
Tiền nhập hàng: [số]
Thu khác: [số]
Chi khác: [số]
LỢI NHUẬN GỘP: [số]"""

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return

    text = msg.text.strip()

    # Bỏ qua tin nhắn quá ngắn hoặc không liên quan
    if len(text) < 5:
        return

    # Gọi Claude phân tích tin nhắn tự do
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            system=CLASSIFY_PROMPT,
            messages=[{"role": "user", "content": text}]
        )
        raw = response.content[0].text.strip()
        data = json.loads(raw)
    except Exception as e:
        return

    loai = data.get("loai", "KHÔNG RÕ")
    if loai == "KHÔNG RÕ":
        return

    du_lieu = data.get("du_lieu", {})
    thieu = data.get("thieu", [])
    xac_nhan = data.get("xac_nhan", "")

    # Lưu giao dịch
    entries.append({
        "time": datetime.now().strftime("%H:%M"),
        "user": msg.from_user.first_name,
        "loai": loai,
        "du_lieu": du_lieu,
        "raw": text
    })

    # Tạo tin xác nhận
    gia = du_lieu.get("gia", "")
    gia_fmt = f"{int(gia):,}đ".replace(",", ".") if str(gia).isdigit() else gia

    if loai == "BÁN":
        icon = "✅"
        tom_tat = f"Ghi nhận bán *{du_lieu.get('sp','')}*"
        if du_lieu.get('kh'): tom_tat += f" cho {du_lieu.get('kh')}"
        if gia_fmt: tom_tat += f" — {gia_fmt}"
        if du_lieu.get('tt'): tom_tat += f" ({du_lieu.get('tt')})"
        if du_lieu.get('dia_chi'): tom_tat += f"\n📍 Giao: {du_lieu.get('dia_chi')}"
    elif loai == "NHẬP":
        icon = "📦"
        tom_tat = f"Ghi nhận nhập *{du_lieu.get('sp','')}*"
        if du_lieu.get('ncc'): tom_tat += f" từ {du_lieu.get('ncc')}"
        if gia_fmt: tom_tat += f" — {gia_fmt}"
    else:
        icon = "💰"
        tc_loai = "Thu" if "thu" in loai.lower() else "Chi"
        tom_tat = f"Ghi nhận {tc_loai}: {du_lieu.get('gc','')}"
        if gia_fmt: tom_tat += f" — {gia_fmt}"

    reply = f"{icon} {tom_tat}"

    # Cảnh báo nếu thiếu thông tin quan trọng
    if thieu:
        reply += f"\n\n⚠️ Còn thiếu: {', '.join(thieu)}"

    await msg.reply_text(reply, parse_mode="Markdown")

async def send_daily_report(bot: Bot):
    if not entries:
        await bot.send_message(
            chat_id=GROUP_ID,
            text="📊 Hôm nay chưa có giao dịch nào được ghi nhận."
        )
        return

    ngay = datetime.now().strftime("%d/%m/%Y")
    all_entries = "\n\n".join([
        f"[{e['time']} - {e['user']} - {e['loai']}]\n{e['raw']}"
        for e in entries
    ])

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        system=REPORT_PROMPT,
        messages=[{"role": "user", "content": f"Ngày {ngay}. Các giao dịch:\n\n{all_entries}"}]
    )

    report = response.content[0].text
    await bot.send_message(
        chat_id=GROUP_ID,
        text=f"📊 *BÁO CÁO CUỐI NGÀY*\n\n{report}",
        parse_mode="Markdown"
    )
    entries.clear()

async def scheduler(bot: Bot):
    while True:
        now = datetime.now()
        if now.hour == 20 and now.minute == 0:
            await send_daily_report(bot)
            await asyncio.sleep(60)
        await asyncio.sleep(30)

async def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    asyncio.create_task(scheduler(app.bot))
    await app.run_polling()

if __name__ == "__main__":
import nest_asyncio
nest_asyncio.apply()
asyncio.get_event_loop().run_until_complete(main())
