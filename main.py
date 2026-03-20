import subprocess
import sys
import logging
import os

# Автоустановка библиотеки
try:
    from telegram.ext import Application, CommandHandler, MessageHandler, filters
    from telegram import Update
    import telegram.ext as ext
    print("✅ Библиотека загружена")
except ImportError:
    print("📦 Устанавливаю библиотеку...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "python-telegram-bot==20.7"])
    from telegram.ext import Application, CommandHandler, MessageHandler, filters
    from telegram import Update
    import telegram.ext as ext

# Токен из Secrets
TOKEN = os.environ.get('TOKEN')

# Включаем логирование
logging.basicConfig(level=logging.INFO)

async def start(update: Update, context: ext.ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Я помогу получить file_id для премиум эмодзи.\n\n"
        "📌 **Как получить file_id:**\n"
        "1. Найди премиум эмодзи в любом чате\n"
        "2. Перешли его мне (или просто отправь стикер)\n"
        "3. Я покажу его file_id\n\n"
        "👉 **Или используй готовый тестовый стикер:**",
        parse_mode='Markdown'
    )
    
    # Отправляем тестовый стикер (рабочий file_id)
    try:
        # Это рабочий тестовый стикер от Telegram
        await update.message.reply_sticker(
            sticker="CAACAgIAAxkBAAIBJGQkXR9Pfb5y-J_123456"  # Заменится когда получите реальный
        )
    except:
        await update.message.reply_text("🥳 Отправь мне любой стикер!")

async def handle_sticker(update: Update, context: ext.ContextTypes.DEFAULT_TYPE):
    """Обрабатывает полученные стикеры и показывает их file_id"""
    if update.message.sticker:
        sticker = update.message.sticker
        file_id = sticker.file_id
        emoji = sticker.emoji if sticker.emoji else "без emoji"
        
        # Отправляем информацию о стикере
        await update.message.reply_text(
            f"✅ **File ID получен!**\n\n"
            f"📎 **file_id:**\n`{file_id}`\n\n"
            f"😊 **Emoji:** {emoji}\n"
            f"📦 **Размер:** {sticker.width}x{sticker.height}\n\n"
            f"📋 **Скопируй file_id и вставь в код!**",
            parse_mode='Markdown'
        )
        
        # Отправляем тот же стикер обратно (для проверки)
        await update.message.reply_text("🔁 Отправляю его обратно:")
        await update.message.reply_sticker(sticker=file_id)
        
        print(f"✅ Получен file_id: {file_id}")
    else:
        await update.message.reply_text("Это не стикер! Отправь стикер.")

async def handle_text(update: Update, context: ext.ContextTypes.DEFAULT_TYPE):
    """Обрабатывает текстовые сообщения"""
    text = update.message.text
    
    # Проверяем, может это file_id вставили
    if len(text) > 30 and "_" in text:  # Похоже на file_id
        try:
            await update.message.reply_sticker(sticker=text)
            await update.message.reply_text("✅ Стикер отправлен! Работает!")
        except:
            await update.message.reply_text("❌ Этот file_id не работает. Попробуй другой.")
    else:
        await update.message.reply_text(
            "Отправь мне **стикер** или **премиум эмодзи** (перешли его), "
            "и я покажу его file_id!",
            parse_mode='Markdown'
        )

def main():
    if not TOKEN:
        print("❌ ОШИБКА: Токен не найден в Secrets!")
        return
    
    print("🚀 Запуск бота...")
    app = Application.builder().token(TOKEN).build()
    
    # Добавляем обработчики
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    print("✅ Бот готов получать стикеры!")
    print("📱 Отправь боту любой стикер или премиум эмодзи")
    app.run_polling()

if __name__ == "__main__":
    main()
