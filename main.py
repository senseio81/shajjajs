import subprocess
import sys
import logging
import os
import asyncio

# Автоустановка
try:
    from telegram.ext import Application, CommandHandler
    from telegram import Update
    import telegram.ext as ext
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "python-telegram-bot==20.7"])
    from telegram.ext import Application, CommandHandler
    from telegram import Update
    import telegram.ext as ext

TOKEN = os.environ.get('BOT_TOKEN')
logging.basicConfig(level=logging.INFO)

# ID сообщения с премиум эмодзи (нужно получить 1 раз)
PREMIUM_MESSAGE_ID = 12345  # ЗАМЕНИТЬ!
CHAT_WITH_PREMIUM = "@some_chat"  # Чат где есть премиум эмодзи

async def start(update: Update, context: ext.ContextTypes.DEFAULT_TYPE):
    # СПОСОБ 1: Скопировать сообщение с премиум эмодзи
    try:
        await context.bot.copy_message(
            chat_id=update.effective_chat.id,
            from_chat_id=CHAT_WITH_PREMIUM,
            message_id=PREMIUM_MESSAGE_ID
        )
        print("✅ Премиум эмодзи отправлено копированием!")
    except Exception as e:
        await update.message.reply_text(f"Ошибка копирования: {e}")
    
    # СПОСОБ 2: Отправить свое сообщение через copy_message
    # Сначала отправляем сообщение с эмодзи СЕБЕ в избранное
    msg = await context.bot.send_message(
        chat_id=update.effective_user.id,
        text='<tg-emoji emoji-id="5217822164362739968">👑</tg-emoji> Премиум текст!',
        parse_mode="HTML"
    )
    
    # Потом копируем его пользователю
    await asyncio.sleep(0.5)
    await context.bot.copy_message(
        chat_id=update.effective_chat.id,
        from_chat_id=update.effective_user.id,
        message_id=msg.message_id
    )

async def save_premium(update: Update, context: ext.ContextTypes.DEFAULT_TYPE):
    """Сохраняет ID сообщения с премиум эмодзи"""
    if update.message.text and '<tg-emoji' in update.message.text:
        # Бот получил сообщение с премиум эмодзи
        print(f"✅ Найдено премиум сообщение! ID: {update.message.message_id}")
        await update.message.reply_text(
            f"ID этого сообщения: `{update.message.message_id}`\n"
            f"Чат: `{update.effective_chat.id}`\n\n"
            "Вставь это в код!",
            parse_mode="Markdown"
        )

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("save", save_premium))
    
    print("🚀 Бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
