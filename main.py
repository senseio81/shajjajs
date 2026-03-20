import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler

TOKEN = os.environ.get("BOT_TOKEN")
logging.basicConfig(level=logging.INFO)

# ID премиум-эмодзи (замени на свой)
PREMIUM_STICKER_ID = "CAACAgIAAxkBAAIBJGQkXR9Pfb5y-J_123456"

async def start(update: Update, context):
    keyboard = [[InlineKeyboardButton("✨ Премиум", callback_data="premium")]]
    await update.message.reply_text(
        "Нажми на кнопку 👇",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

async def button_handler(update: Update, context):
    query = update.callback_query
    await query.answer()

    if query.data == "premium":
        await query.message.reply_sticker(sticker=PREMIUM_STICKER_ID)
        await query.message.reply_text(
            "<b>Твой премиум-эмодзи 🔥</b>",
            parse_mode="HTML",
        )

def main():
    if not TOKEN:
        print("❌ Ошибка: BOT_TOKEN не найден в Secrets!")
        return
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    print("✅ Бот запущен")
    app.run_polling()

if __name__ == "__main__":
    main()
