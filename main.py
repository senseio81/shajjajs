import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler

TOKEN = os.environ.get("BOT_TOKEN")
logging.basicConfig(level=logging.INFO)

# ID твоего премиум-эмодзи
PREMIUM_STICKER_ID = "5251203410396458957"

async def start(update: Update, context):
    keyboard = [[InlineKeyboardButton("Премиум", callback_data="premium")]]
    await update.message.reply_text(
        "Нажми кнопку:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

async def button(update: Update, context):
    query = update.callback_query
    await query.answer()
    await query.message.reply_sticker(sticker=PREMIUM_STICKER_ID)

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.run_polling()

if __name__ == "__main__":
    main()
