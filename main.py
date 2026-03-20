import subprocess
import sys
import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler

# Автоустановка
try:
    from telegram.ext import Application, CommandHandler, CallbackQueryHandler
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "python-telegram-bot==20.7"])
    from telegram.ext import Application, CommandHandler, CallbackQueryHandler
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup

TOKEN = os.environ.get('TOKEN')
logging.basicConfig(level=logging.INFO)

# ID твоего премиум-эмодзи
PREMIUM_EMOJI_ID = "5251203410396458957"

async def start(update: Update, context):
    # Кнопка с премиум-эмодзи внутри
    keyboard = [[InlineKeyboardButton(
        f'<tg-emoji emoji-id="{PREMIUM_EMOJI_ID}">🔒</tg-emoji> Премиум',
        callback_data="premium"
    )]]
    
    await update.message.reply_text(
        "Нажми кнопку:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )

async def button(update: Update, context):
    query = update.callback_query
    await query.answer()
    
    # Ответ с премиум-эмодзи в тексте (тоже через тег)
    await query.message.reply_text(
        f'<tg-emoji emoji-id="{PREMIUM_EMOJI_ID}">🔒</tg-emoji> Твой премиум-эмодзи!',
        parse_mode="HTML"
    )

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    
    print("🚀 Бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
