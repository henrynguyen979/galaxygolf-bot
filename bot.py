import os, asyncio
from datetime import datetime
from telegram import Update, Bot
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
import anthropic

TOKEN = os.environ["BOT_TOKEN"]
GROUP_ID = int(os.environ["GROUP_ID"])
ANTHROPIC_KEY = os.environ["ANTHROPIC_KEY"]

entries = []

SYSTEM_PROMPT = """Bạn là trợ lý nhật ký bán hàng Galaxy Golf Nha Trang.
Nhiệm vụ 1 - Xác nhận giao dịch: Khi nhận tin nhắn có format BÁN/NHẬP/THU CHI,
trả lời xác nhận ngắn gọn bằng emoji + tóm tắt 1 dòng + số tiền.
Ví dụ: ✅ Ghi nhận bán Titleist TS2 3-Wood cho anh Hùng — 3.500.000đ (CK)

Nhiệm vụ 2 - Báo cáo cuối ngày: Khi nhận danh sách giao dịch trong ngày,
tạo báo cáo tổng hợp đầy đủ theo format chuẩn Galaxy Golf."""

client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return
    text = msg.text.strip()
    first_line = text.split('\n')[0].upper()

    if not any(first_line.startswith(kw) for kw in ['BÁN', 'BAN', 'NHẬP', 'NHAP', 'THU CHI']):
        return

    entries.append({
        "time": datetime.now().strftime("%H:%M"),
        "user": msg.from_user.first_name,
        "text": text
    })

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=150,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"Xác nhận giao dịch này:\n{text}"}]
    )
    await msg.reply_text(response.content[0].text)

async def send_daily_report(bot: Bot):
    if not entries:
        await bot.send_message(chat_id=GROUP_ID, text="📊 Hôm nay chưa có giao dịch nào được ghi nhận.")
        return

    all_entries = "\n\n".join([f"[{e['time']} - {e['user']}]\n{e['text']}" for e in entries])

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"Tạo báo cáo cuối ngày từ các giao dịch sau:\n\n{all_entries}"}]
    )

    report = response.content[0].text
    await bot.send_message(chat_id=GROUP_ID, text=f"📊 *BÁO CÁO CUỐI NGÀY*\n\n{report}", parse_mode="Markdown")
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
    asyncio.run(main())
