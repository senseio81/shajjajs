import asyncio
import logging
from datetime import datetime
import os

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode
import asyncpg

TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

logging.basicConfig(level=logging.INFO)

bot = Bot(token=TOKEN)
dp = Dispatcher()

async def init_db():
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("DROP TABLE IF EXISTS users")
    await conn.execute("""
        CREATE TABLE users (
            id BIGINT PRIMARY KEY,
            username TEXT,
            balance INTEGER DEFAULT 0,
            total_bet INTEGER DEFAULT 0,
            registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.close()

def get_rank(total_bet):
    if total_bet < 50:
        return "👾 Новичок", 50
    elif total_bet < 500:
        return "🤖 Олд", 500
    elif total_bet < 5000:
        return "👑 Профи", 5000
    else:
        return "💎 Герцог", 50000

def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎲 Играть"), KeyboardButton(text="💳 Профиль")]
        ],
        resize_keyboard=True
    )

def get_profile_inline():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💳 Пополнить", callback_data="deposit"),
                InlineKeyboardButton(text="🎉 Вывести", callback_data="withdraw")
            ],
            [InlineKeyboardButton(text="🧩 Реферальная программа", callback_data="referral")]
        ]
    )

@dp.message(Command("start"))
async def start_command(message: Message):
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("""
        INSERT INTO users (id, username) VALUES ($1, $2)
        ON CONFLICT (id) DO NOTHING
    """, message.from_user.id, message.from_user.username)
    await conn.close()
    
    await message.answer(
        "<b>🎉 Добро пожаловать в Hot Dice 🎲</b>\n\nПоддержка: @MNGhotdice",
        parse_mode=ParseMode.HTML,
        reply_markup=get_main_keyboard()
    )

@dp.message(F.text == "💳 Профиль")
async def profile_command(message: Message):
    conn = await asyncpg.connect(DATABASE_URL)
    user = await conn.fetchrow("SELECT * FROM users WHERE id = $1", message.from_user.id)
    await conn.close()
    
    if not user:
        await message.answer("Ошибка. Напишите /start")
        return
    
    rank_name, next_threshold = get_rank(user["total_bet"])
    remaining = max(0, next_threshold - user["total_bet"])
    reg_date = user["registered_at"].strftime("%d.%m.%Y")
    
    await message.answer("🎲")
    
    profile_text = (
        f"<b>🔐 Ваш профиль</b>\n"
        f"└ Текущий баланс: {user['balance']}$\n\n"
        f"<blockquote>Зарегистрирован: {reg_date}</blockquote>\n"
        f"<b>Ваш ранг: {rank_name}</b>\n"
        f" ├ Оборот: {user['total_bet']}$\n"
        f" └ Осталось: {remaining}$ из {next_threshold}$"
    )
    
    await message.answer(
        profile_text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_profile_inline()
    )

@dp.message(F.text == "🎲 Играть")
async def play_dummy(message: Message):
    await message.answer("🎲 Игра в разработке 🛠")

@dp.callback_query()
async def handle_callbacks(callback: types.CallbackQuery):
    await callback.answer("🚧 В разработке", show_alert=True)

@dp.message(Command("cleardb"))
async def clear_db(message: Message):
    if message.from_user.id != 123456789:
        await message.answer("🚫 Нет доступа")
        return
    
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("DELETE FROM users")
    await conn.close()
    
    await message.answer("✅ База данных очищена")

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
