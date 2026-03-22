import asyncio
import logging
import os
import aiohttp
import random
from datetime import datetime, timedelta
from io import StringIO
from collections import defaultdict
import time

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.enums import ParseMode
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
import asyncpg

TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
CRYPTO_TOKEN = os.getenv("CRYPTO_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

logging.basicConfig(level=logging.INFO)

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

user_invoice_messages = {}
rate_limit_dict = defaultdict(list)
user_plane_games = {}

win_quotes = [
    "В этот раз удача выбрала тебя. Поздравляю!",
    "Твой риск был оправдан — забирай выигрыш!",
    "Фортуна сегодня работает на тебя. Не останавливайся!",
    "Идеальный момент — ты его поймал. Отлично сыграно!",
    "Казино помнит таких игроков. Продолжай в том же духе!",
    "Ты читаешь игру как открытую книгу. Великолепно!",
    "Даже крупье аплодирует твоему ходу. Шикарная ставка!",
    "Интуиция не подвела — это твой день!"
]

lose_quotes = [
    "Сегодня не твой день, но это всего лишь повод взять паузу.",
    "Даже лучшие игроки проигрывают. Главное — вернуться сильнее.",
    "Удача любит упорных. Следующая ставка будет твоей.",
    "Проигрыш — это не поражение, а опыт. Идём дальше.",
    "Казино не дремлет, но и ты не сдавайся. Следующий ход за тобой!",
    "Фортуна отвлеклась, но она обязательно вернётся. Продолжай играть!",
    "Это всего лишь разминка. Настоящая игра только начинается!",
    "Не позволяй одному броску испортить настрой. Впереди джекпот!"
]

casino_quotes = win_quotes + lose_quotes

def rate_limit(limit: int, period: int = 1):
    def decorator(func):
        async def wrapper(event, *args, **kwargs):
            user_id = None
            if isinstance(event, Message):
                user_id = event.from_user.id
            elif isinstance(event, types.CallbackQuery):
                user_id = event.from_user.id
            else:
                return await func(event, *args, **kwargs)
            
            now = time.time()
            user_requests = rate_limit_dict[user_id]
            user_requests = [t for t in user_requests if now - t < period]
            if len(user_requests) >= limit:
                if isinstance(event, Message):
                    await event.answer("⏳ Слишком много запросов, подождите немного")
                elif isinstance(event, types.CallbackQuery):
                    await event.answer("⏳ Слишком много запросов, подождите немного", show_alert=True)
                return
            user_requests.append(now)
            rate_limit_dict[user_id] = user_requests
            return await func(event, *args, **kwargs)
        return wrapper
    return decorator

class DepositStates(StatesGroup):
    waiting_for_amount = State()

class WithdrawStates(StatesGroup):
    waiting_for_amount = State()

class BroadcastStates(StatesGroup):
    waiting_for_message = State()

class GameStates(StatesGroup):
    waiting_for_bet = State()
    waiting_for_bowling_bet = State()
    waiting_for_darts_bet = State()
    waiting_for_plane_bet = State()

async def init_db():
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id BIGINT PRIMARY KEY,
            username TEXT,
            balance INTEGER DEFAULT 0,
            total_bet INTEGER DEFAULT 0,
            registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            referrer_id BIGINT,
            referral_earnings INTEGER DEFAULT 0
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS withdraw_requests (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            amount INTEGER,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processed_at TIMESTAMP
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            action TEXT,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_referrer_id ON users(referrer_id)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_withdraw_requests_user_id ON withdraw_requests(user_id)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_user_id ON logs(user_id)")
    await conn.close()

async def log_action(user_id: int, action: str, details: str = ""):
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("""
        INSERT INTO logs (user_id, action, details) VALUES ($1, $2, $3)
    """, user_id, action, details)
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

def get_referral_inline():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_profile")]
        ]
    )

def get_deposit_methods_inline():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎉 CryptoBot", callback_data="crypto_bot")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_profile")]
        ]
    )

def get_cancel_inline():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔐 Отменить", callback_data="cancel_deposit")]
        ]
    )

def get_cancel_withdraw_inline():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔐 Отменить", callback_data="cancel_withdraw")]
        ]
    )

def get_withdraw_request_inline(request_id: int, user_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔐 Логи", callback_data=f"admin_logs_{user_id}"),
                InlineKeyboardButton(text="💳 Подтвердить", callback_data=f"admin_approve_{request_id}")
            ],
            [InlineKeyboardButton(text="💳 Отклонить", callback_data=f"admin_reject_{request_id}")]
        ]
    )

def get_profile_only_inline():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔐 Профиль", callback_data="back_to_profile")]
        ]
    )

def get_games_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🎲 Кубик", callback_data="game_dice"),
                InlineKeyboardButton(text="🎯 Дартс", callback_data="game_darts")
            ],
            [
                InlineKeyboardButton(text="🚀 Ракетка", callback_data="game_plane"),
                InlineKeyboardButton(text="🎳 Боулинг", callback_data="game_bowling")
            ],
            [InlineKeyboardButton(text="« Назад", callback_data="back_to_profile")]
        ]
    )

def get_dice_modes():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Четное", callback_data="dice_even"),
                InlineKeyboardButton(text="Нечетное", callback_data="dice_odd")
            ],
            [
                InlineKeyboardButton(text="Сектора", callback_data="dice_sector"),
                InlineKeyboardButton(text="Больше/Меньше", callback_data="dice_overunder")
            ],
            [InlineKeyboardButton(text="« Назад", callback_data="back_to_games")]
        ]
    )

def get_dice_overunder():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Больше 3", callback_data="overunder_over"),
                InlineKeyboardButton(text="Меньше 4", callback_data="overunder_under")
            ],
            [InlineKeyboardButton(text="« Назад", callback_data="back_to_dice_modes")]
        ]
    )

def get_dice_sectors():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Сектор 1", callback_data="sector_1"),
                InlineKeyboardButton(text="Сектор 2", callback_data="sector_2"),
                InlineKeyboardButton(text="Сектор 3", callback_data="sector_3")
            ],
            [
                InlineKeyboardButton(text="Сектор 4", callback_data="sector_4"),
                InlineKeyboardButton(text="Сектор 5", callback_data="sector_5"),
                InlineKeyboardButton(text="Сектор 6", callback_data="sector_6")
            ],
            [InlineKeyboardButton(text="« Назад", callback_data="back_to_dice_modes")]
        ]
    )

def get_bowling_modes():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Больше 3", callback_data="bowling_over"),
                InlineKeyboardButton(text="Меньше 4", callback_data="bowling_under")
            ],
            [InlineKeyboardButton(text="Страйк", callback_data="bowling_strike")],
            [InlineKeyboardButton(text="« Назад", callback_data="back_to_games")]
        ]
    )

def get_darts_modes():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Красный", callback_data="darts_red"),
                InlineKeyboardButton(text="Белый", callback_data="darts_white")
            ],
            [
                InlineKeyboardButton(text="Центр", callback_data="darts_center"),
                InlineKeyboardButton(text="Отскок", callback_data="darts_bounce")
            ],
            [InlineKeyboardButton(text="« Назад", callback_data="back_to_games")]
        ]
    )

def get_plane_buttons():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🟢 ЗАБРАТЬ", callback_data="plane_cashout"),
                InlineKeyboardButton(text="❌ ВЫЙТИ", callback_data="plane_exit")
            ]
        ]
    )

def get_bet_cancel_inline():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔐 Отменить", callback_data="cancel_bet")]
        ]
    )

def get_make_bet_inline():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💎 Сделать ставку", callback_data="make_bet")]
        ]
    )

def generate_crash():
    r = random.random()
    if r < 0.40:
        return round(random.uniform(1.00, 1.30), 2)
    elif r < 0.60:
        return round(random.uniform(1.31, 1.50), 2)
    elif r < 0.80:
        return round(random.uniform(1.51, 2.00), 2)
    elif r < 0.88:
        return round(random.uniform(2.01, 3.00), 2)
    elif r < 0.93:
        return round(random.uniform(3.01, 5.00), 2)
    elif r < 0.97:
        return round(random.uniform(5.01, 10.00), 2)
    elif r < 0.995:
        return round(random.uniform(10.01, 50.00), 2)
    else:
        return round(random.uniform(50.01, 100.00), 2)

async def get_user_stats(user_id: int):
    conn = await asyncpg.connect(DATABASE_URL)
    
    total_games = await conn.fetchval("SELECT COUNT(*) FROM logs WHERE user_id = $1 AND action IN ('dice_win', 'dice_lose', 'bowling_win', 'bowling_lose', 'darts_win', 'darts_lose', 'plane_win', 'plane_lose')", user_id) or 0
    
    favorite = await conn.fetchrow("""
        SELECT 
            CASE 
                WHEN action LIKE 'dice%' THEN '🎲 Кубик'
                WHEN action LIKE 'bowling%' THEN '🎳 Боулинг'
                WHEN action LIKE 'darts%' THEN '🎯 Дартс'
                WHEN action LIKE 'plane%' THEN '🚀 Ракетка'
            END as game,
            COUNT(*) as count
        FROM logs 
        WHERE user_id = $1 AND action IN ('dice_win', 'dice_lose', 'bowling_win', 'bowling_lose', 'darts_win', 'darts_lose', 'plane_win', 'plane_lose')
        GROUP BY game
        ORDER BY count DESC
        LIMIT 1
    """, user_id)
    favorite_game = favorite["game"] if favorite else "—"
    
    max_win = await conn.fetchval("""
        SELECT MAX(CAST(split_part(details, 'Выигрыш ', 2) AS FLOAT))
        FROM logs 
        WHERE user_id = $1 AND action IN ('dice_win', 'bowling_win', 'darts_win', 'plane_win')
    """, user_id) or 0
    
    total_bet = await conn.fetchval("SELECT total_bet FROM users WHERE id = $1", user_id) or 0
    
    await conn.close()
    
    return total_games, favorite_game, max_win, total_bet

async def show_user_profile(message: Message, target_user_id: int):
    conn = await asyncpg.connect(DATABASE_URL)
    user = await conn.fetchrow("SELECT * FROM users WHERE id = $1", target_user_id)
    await conn.close()
    
    if not user:
        await message.answer("❌ Пользователь не найден")
        return
    
    username = user["username"] if user["username"] else f"ID:{target_user_id}"
    total_games, favorite_game, max_win, total_bet = await get_user_stats(target_user_id)
    
    profile_text = (
        f"<b>👤 Пользователь › {username}</b>\n"
        f" ├ Всего игр: {total_games} шт.\n"
        f" ├ Избранное: {favorite_game}\n"
        f" └ Максимальный вин: {max_win:.2f}$\n\n"
        f"<b>💸 Оборот: {total_bet/100:.2f}$</b>"
    )
    
    await message.answer(profile_text, parse_mode=ParseMode.HTML)

@dp.message(Command("start"))
async def start_command(message: Message):
    args = message.text.split()
    
    if len(args) > 1 and args[1].startswith("user_"):
        try:
            target_user_id = int(args[1].split("_")[1])
            await show_user_profile(message, target_user_id)
            return
        except:
            pass
    
    conn = await asyncpg.connect(DATABASE_URL)
    
    user = await conn.fetchrow("SELECT * FROM users WHERE id = $1", message.from_user.id)
    if not user:
        await conn.execute("""
            INSERT INTO users (id, username) VALUES ($1, $2)
        """, message.from_user.id, message.from_user.username)
        await log_action(message.from_user.id, "start", "Регистрация в боте")
    
    await conn.close()
    
    await message.answer(
        "<b>🎉 Добро пожаловать в Hot Dice 🎲</b>\n\nПоддержка: @MNGhotdice",
        parse_mode=ParseMode.HTML,
        reply_markup=get_main_keyboard()
    )

@rate_limit(limit=10)
@dp.message(F.text == "💳 Профиль")
async def profile_command(message: Message):
    await message.reply_dice(emoji="🎲")
    
    conn = await asyncpg.connect(DATABASE_URL)
    user = await conn.fetchrow("SELECT * FROM users WHERE id = $1", message.from_user.id)
    await conn.close()
    
    if not user:
        await message.answer("Ошибка. Напишите /start")
        return
    
    await log_action(message.from_user.id, "profile", f"Просмотр профиля, баланс: {user['balance']/100}$")
    
    rank_name, next_threshold = get_rank(user["total_bet"])
    remaining = max(0, next_threshold - user["total_bet"])
    reg_date = user["registered_at"].strftime("%d.%m.%Y")
    
    profile_text = (
        f"<b>🔐 Ваш профиль</b>\n"
        f"└ Текущий баланс: {user['balance']/100}$\n\n"
        f"<blockquote>Зарегистрирован: {reg_date}</blockquote>\n"
        f"<b>Ваш ранг: {rank_name}</b>\n"
        f" ├ Оборот: {user['total_bet']/100}$\n"
        f" └ Осталось: {remaining/100}$ из {next_threshold/100}$"
    )
    
    photo = FSInputFile("IMG_0760.jpeg")
    await message.answer_photo(
        photo=photo,
        caption=profile_text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_profile_inline()
    )

@rate_limit(limit=10)
@dp.message(F.text == "🎲 Играть")
async def games_menu(message: Message):
    await message.reply("💎")
    
    photo = FSInputFile("IMG_0754.jpeg")
    await message.answer_photo(
        photo=photo,
        caption="<b>🎉 Раздел доступных режимов</b>\n└ Выберите игру:",
        parse_mode=ParseMode.HTML,
        reply_markup=get_games_menu()
    )

@rate_limit(limit=10)
@dp.callback_query(F.data == "game_dice")
async def dice_start(callback: types.CallbackQuery):
    conn = await asyncpg.connect(DATABASE_URL)
    user = await conn.fetchrow("SELECT * FROM users WHERE id = $1", callback.from_user.id)
    await conn.close()
    
    if user["balance"] < 30:
        await callback.answer("💳 Минимальная ставка 0.30 USDT, пополните баланс", show_alert=True)
        return
    
    photo = FSInputFile("IMG_0754.jpeg")
    await callback.message.edit_media(
        types.InputMediaPhoto(
            media=photo,
            caption="<b>🎲 Выберите режим игры:</b>",
            parse_mode=ParseMode.HTML
        ),
        reply_markup=get_dice_modes()
    )
    await callback.answer()

@rate_limit(limit=10)
@dp.callback_query(F.data == "game_darts")
async def darts_menu(callback: types.CallbackQuery):
    conn = await asyncpg.connect(DATABASE_URL)
    user = await conn.fetchrow("SELECT * FROM users WHERE id = $1", callback.from_user.id)
    await conn.close()
    
    if user["balance"] < 30:
        await callback.answer("💳 Минимальная ставка 0.30 USDT, пополните баланс", show_alert=True)
        return
    
    photo = FSInputFile("IMG_0773.jpeg")
    await callback.message.edit_media(
        types.InputMediaPhoto(
            media=photo,
            caption="<b>🎯 Выберите сектор дартса:</b>",
            parse_mode=ParseMode.HTML
        ),
        reply_markup=get_darts_modes()
    )
    await callback.answer()

@rate_limit(limit=10)
@dp.callback_query(F.data == "game_plane")
async def plane_start(callback: types.CallbackQuery, state: FSMContext):
    conn = await asyncpg.connect(DATABASE_URL)
    user = await conn.fetchrow("SELECT * FROM users WHERE id = $1", callback.from_user.id)
    await conn.close()
    
    if user["balance"] < 30:
        await callback.answer("💳 Минимальная ставка 0.30 USDT, пополните баланс", show_alert=True)
        return
    
    bet_text = (
        f"<b>🚀 РАКЕТКА</b>\n\n"
        f"<blockquote>Коэффициент: 1.00x</blockquote>\n"
        f"<blockquote>Ваш баланс: {user['balance']/100} USDT</blockquote>\n\n"
        f"Введите сумму ставки:"
    )
    
    photo = FSInputFile("IMG_0775.jpeg")
    await callback.message.edit_media(
        types.InputMediaPhoto(
            media=photo,
            caption=bet_text,
            parse_mode=ParseMode.HTML
        ),
        reply_markup=get_bet_cancel_inline()
    )
    await state.set_state(GameStates.waiting_for_plane_bet)
    await callback.answer()

@rate_limit(limit=10)
@dp.callback_query(F.data == "game_bowling")
async def bowling_menu(callback: types.CallbackQuery):
    conn = await asyncpg.connect(DATABASE_URL)
    user = await conn.fetchrow("SELECT * FROM users WHERE id = $1", callback.from_user.id)
    await conn.close()
    
    if user["balance"] < 30:
        await callback.answer("💳 Минимальная ставка 0.30 USDT, пополните баланс", show_alert=True)
        return
    
    photo = FSInputFile("IMG_0772.jpeg")
    await callback.message.edit_media(
        types.InputMediaPhoto(
            media=photo,
            caption="<b>🎳 Выберите режим игры:</b>",
            parse_mode=ParseMode.HTML
        ),
        reply_markup=get_bowling_modes()
    )
    await callback.answer()

@rate_limit(limit=10)
@dp.callback_query(F.data == "back_to_games")
async def back_to_games(callback: types.CallbackQuery):
    photo = FSInputFile("IMG_0754.jpeg")
    await callback.message.edit_media(
        types.InputMediaPhoto(
            media=photo,
            caption="<b>🎉 Раздел доступных режимов</b>\n└ Выберите игру:",
            parse_mode=ParseMode.HTML
        ),
        reply_markup=get_games_menu()
    )
    await callback.answer()

@rate_limit(limit=10)
@dp.callback_query(F.data == "dice_even")
async def dice_even(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(game_mode="even", coeff=1.85)
    await show_bet_request(callback.message, callback.from_user.id, state, "Четное", 1.85)

@rate_limit(limit=10)
@dp.callback_query(F.data == "dice_odd")
async def dice_odd(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(game_mode="odd", coeff=1.85)
    await show_bet_request(callback.message, callback.from_user.id, state, "Нечетное", 1.85)

@rate_limit(limit=10)
@dp.callback_query(F.data == "dice_sector")
async def dice_sector(callback: types.CallbackQuery):
    photo = FSInputFile("IMG_0754.jpeg")
    await callback.message.edit_media(
        types.InputMediaPhoto(
            media=photo,
            caption="<b>🎲 Выберите сектор:</b>",
            parse_mode=ParseMode.HTML
        ),
        reply_markup=get_dice_sectors()
    )
    await callback.answer()

@rate_limit(limit=10)
@dp.callback_query(F.data == "dice_overunder")
async def dice_overunder(callback: types.CallbackQuery):
    photo = FSInputFile("IMG_0754.jpeg")
    await callback.message.edit_media(
        types.InputMediaPhoto(
            media=photo,
            caption="<b>🎲 Выберите режим:</b>",
            parse_mode=ParseMode.HTML
        ),
        reply_markup=get_dice_overunder()
    )
    await callback.answer()

@rate_limit(limit=10)
@dp.callback_query(F.data.startswith("sector_"))
async def sector_selected(callback: types.CallbackQuery, state: FSMContext):
    sector_num = int(callback.data.split("_")[1])
    await state.update_data(game_mode="sector", sector=sector_num, coeff=5.0)
    await show_bet_request(callback.message, callback.from_user.id, state, f"Сектор {sector_num}", 5.0)

@rate_limit(limit=10)
@dp.callback_query(F.data == "overunder_over")
async def overunder_over(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(game_mode="over", coeff=2.0)
    await show_bet_request(callback.message, callback.from_user.id, state, "Больше 3", 2.0)

@rate_limit(limit=10)
@dp.callback_query(F.data == "overunder_under")
async def overunder_under(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(game_mode="under", coeff=2.0)
    await show_bet_request(callback.message, callback.from_user.id, state, "Меньше 4", 2.0)

@rate_limit(limit=10)
@dp.callback_query(F.data == "back_to_dice_modes")
async def back_to_dice_modes(callback: types.CallbackQuery):
    photo = FSInputFile("IMG_0754.jpeg")
    await callback.message.edit_media(
        types.InputMediaPhoto(
            media=photo,
            caption="<b>🎲 Выберите режим игры:</b>",
            parse_mode=ParseMode.HTML
        ),
        reply_markup=get_dice_modes()
    )
    await callback.answer()

@rate_limit(limit=10)
@dp.callback_query(F.data.startswith("bowling_"))
async def bowling_mode_selected(callback: types.CallbackQuery, state: FSMContext):
    mode = callback.data.split("_")[1]
    
    if mode == "over":
        coeff = 1.45
        mode_text = "Больше 3 кеглей"
    elif mode == "under":
        coeff = 3.20
        mode_text = "Меньше 4 кеглей"
    elif mode == "strike":
        coeff = 9.0
        mode_text = "Страйк"
    else:
        return
    
    await state.update_data(game_type="bowling", bowling_mode=mode, coeff=coeff, mode_text=mode_text)
    
    conn = await asyncpg.connect(DATABASE_URL)
    user = await conn.fetchrow("SELECT balance FROM users WHERE id = $1", callback.from_user.id)
    await conn.close()
    
    bet_text = (
        f"<b>🎳 Боулинг - {mode_text}</b>\n\n"
        f"<blockquote>Коэффициент: {coeff}x</blockquote>\n"
        f"<blockquote>Ваш баланс: {user['balance']/100} USDT</blockquote>\n\n"
        f"Введите сумму ставки:"
    )
    
    photo = FSInputFile("IMG_0772.jpeg")
    await callback.message.edit_media(
        types.InputMediaPhoto(
            media=photo,
            caption=bet_text,
            parse_mode=ParseMode.HTML
        ),
        reply_markup=get_bet_cancel_inline()
    )
    await state.set_state(GameStates.waiting_for_bowling_bet)
    await callback.answer()

@rate_limit(limit=10)
@dp.callback_query(F.data.startswith("darts_"))
async def darts_mode_selected(callback: types.CallbackQuery, state: FSMContext):
    mode = callback.data.split("_")[1]
    
    if mode == "red":
        coeff = 2.2
        mode_text = "Красный сектор"
        win_condition = [1, 2]
    elif mode == "white":
        coeff = 2.2
        mode_text = "Белый сектор"
        win_condition = [3, 4]
    elif mode == "center":
        coeff = 5.5
        mode_text = "Центр"
        win_condition = [5]
    elif mode == "bounce":
        coeff = 5.5
        mode_text = "Отскок"
        win_condition = [6]
    else:
        return
    
    await state.update_data(
        game_type="darts",
        darts_mode=mode,
        coeff=coeff,
        mode_text=mode_text,
        win_condition=win_condition
    )
    
    conn = await asyncpg.connect(DATABASE_URL)
    user = await conn.fetchrow("SELECT balance FROM users WHERE id = $1", callback.from_user.id)
    await conn.close()
    
    bet_text = (
        f"<b>🎯 Дартс - {mode_text}</b>\n\n"
        f"<blockquote>Коэффициент: {coeff}x</blockquote>\n"
        f"<blockquote>Ваш баланс: {user['balance']/100} USDT</blockquote>\n\n"
        f"Введите сумму ставки:"
    )
    
    photo = FSInputFile("IMG_0773.jpeg")
    await callback.message.edit_media(
        types.InputMediaPhoto(
            media=photo,
            caption=bet_text,
            parse_mode=ParseMode.HTML
        ),
        reply_markup=get_bet_cancel_inline()
    )
    await state.set_state(GameStates.waiting_for_darts_bet)
    await callback.answer()

@dp.message(GameStates.waiting_for_plane_bet)
async def process_plane_bet(message: Message, state: FSMContext):
    try:
        bet = float(message.text.replace(",", "."))
        if bet < 0.30:
            await message.answer("❌ Минимальная ставка 0.30 USDT")
            return
    except:
        await message.answer("❌ Введите число")
        return
    
    conn = await asyncpg.connect(DATABASE_URL)
    user = await conn.fetchrow("SELECT * FROM users WHERE id = $1", message.from_user.id)
    
    if user["balance"] < int(bet * 100):
        await conn.close()
        await message.answer("❌ Недостаточно средств")
        await state.clear()
        return
    
    await conn.execute("UPDATE users SET balance = balance - $1 WHERE id = $2", int(bet * 100), message.from_user.id)
    await conn.close()
    
    crash_point = generate_crash()
    
    game_text = (
        f"🚀 РАКЕТКА\n\n"
        f"<blockquote>Текущий коэффициент: 1.00x</blockquote>\n"
        f"<blockquote>Ставка: {bet} USDT</blockquote>\n"
        f"<blockquote>Потенциальный выигрыш: {bet:.2f} USDT</blockquote>\n\n"
        f"<blockquote>{random.choice(casino_quotes)}</blockquote>"
    )
    
    msg = await message.answer(
        game_text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_plane_buttons()
    )
    
    user_plane_games[message.from_user.id] = {
        "bet": bet,
        "crash_point": crash_point,
        "current_multiplier": 1.00,
        "active": True,
        "message_id": msg.message_id,
        "chat_id": message.chat.id
    }
    
    await state.clear()
    
    asyncio.create_task(plane_game_loop(message.from_user.id))

async def plane_game_loop(user_id):
    multiplier = 1.00
    
    while user_id in user_plane_games and user_plane_games[user_id]["active"]:
        await asyncio.sleep(0.8)
        
        if user_id not in user_plane_games or not user_plane_games[user_id]["active"]:
            break
        
        increase = random.uniform(0.05, 0.30)
        multiplier += increase
        user_plane_games[user_id]["current_multiplier"] = multiplier
        
        bet = user_plane_games[user_id]["bet"]
        win_amount = bet * multiplier
        crash_point = user_plane_games[user_id]["crash_point"]
        
        game_text = (
            f"🚀 РАКЕТКА\n\n"
            f"<blockquote>Текущий коэффициент: {multiplier:.2f}x</blockquote>\n"
            f"<blockquote>Ставка: {bet} USDT</blockquote>\n"
            f"<blockquote>Потенциальный выигрыш: {win_amount:.2f} USDT</blockquote>\n\n"
            f"<blockquote>{random.choice(casino_quotes)}</blockquote>"
        )
        
        try:
            await bot.edit_message_text(
                game_text,
                chat_id=user_plane_games[user_id]["chat_id"],
                message_id=user_plane_games[user_id]["message_id"],
                parse_mode=ParseMode.HTML,
                reply_markup=get_plane_buttons()
            )
        except:
            pass
        
        if multiplier >= crash_point:
            data = user_plane_games.pop(user_id)
            
            conn = await asyncpg.connect(DATABASE_URL)
            await conn.execute("UPDATE users SET total_bet = total_bet + $1 WHERE id = $2", int(data["bet"] * 100), user_id)
            await conn.close()
            
            quote = random.choice(lose_quotes)
            result_text = (
                f"💥 <b>РАКЕТА УЛЕТЕЛА!</b>\n\n"
                f"<blockquote>Коэффициент: {crash_point:.2f}x</blockquote>\n"
                f"<blockquote>Ставка: {data['bet']} USDT</blockquote>\n"
                f"<blockquote>Вы проиграли!</blockquote>\n"
                f"<blockquote>{quote}</blockquote>"
            )
            
            await bot.send_message(
                data["chat_id"],
                result_text,
                parse_mode=ParseMode.HTML,
                reply_markup=get_make_bet_inline()
            )
            
            await log_action(user_id, "plane_lose", f"Проигрыш {data['bet']}$ (краш на {crash_point:.2f}x)")
            break

@dp.callback_query(F.data == "plane_cashout")
async def plane_cashout(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    if user_id not in user_plane_games:
        await callback.answer("Игра не найдена", show_alert=True)
        return
    
    data = user_plane_games.pop(user_id)
    bet = data["bet"]
    multiplier = data["current_multiplier"]
    win_amount = bet * multiplier
    
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("UPDATE users SET balance = balance + $1, total_bet = total_bet + $2 WHERE id = $3", 
                      int(win_amount * 100), int(bet * 100), user_id)
    await conn.close()
    
    quote = random.choice(win_quotes)
    result_text = (
        f"✅ <b>ВЫ ВЫИГРАЛИ!</b>\n\n"
        f"<blockquote>Ставка: {bet} USDT</blockquote>\n"
        f"<blockquote>Коэффициент: {multiplier:.2f}x</blockquote>\n"
        f"<blockquote>Выигрыш: {win_amount:.2f} USDT</blockquote>\n"
        f"<blockquote>{quote}</blockquote>"
    )
    
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        result_text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_make_bet_inline()
    )
    
    await log_action(user_id, "plane_win", f"Выигрыш {win_amount}$ (ставка {bet}$, множитель {multiplier:.2f}x)")
    await callback.answer()

@dp.callback_query(F.data == "plane_exit")
async def plane_exit(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    if user_id in user_plane_games:
        data = user_plane_games.pop(user_id)
        bet = data["bet"]
        
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute("UPDATE users SET balance = balance + $1 WHERE id = $2", int(bet * 100), user_id)
        await conn.close()
        
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer("❌ Вы вышли из игры. Ставка возвращена.")
    
    await callback.answer()

@dp.message(GameStates.waiting_for_bowling_bet)
async def process_bowling_bet(message: Message, state: FSMContext):
    try:
        bet = float(message.text.replace(",", "."))
        if bet < 0.30:
            await message.answer("❌ Минимальная ставка 0.30 USDT")
            return
    except:
        await message.answer("❌ Введите число")
        return
    
    data = await state.get_data()
    bowling_mode = data.get("bowling_mode")
    coeff = data.get("coeff")
    mode_text = data.get("mode_text")
    
    conn = await asyncpg.connect(DATABASE_URL)
    user = await conn.fetchrow("SELECT * FROM users WHERE id = $1", message.from_user.id)
    
    if user["balance"] < int(bet * 100):
        await conn.close()
        await message.answer("❌ Недостаточно средств")
        await state.clear()
        return
    
    await conn.execute("UPDATE users SET balance = balance - $1 WHERE id = $2", int(bet * 100), message.from_user.id)
    await conn.close()
    
    bowling_msg = await message.reply_dice(emoji="🎳")
    await asyncio.sleep(2)
    knocked = bowling_msg.dice.value
    
    if bowling_mode == "over":
        win = knocked > 3
        win_text = f"Сбито кеглей: {knocked}"
    elif bowling_mode == "under":
        win = knocked < 4
        win_text = f"Сбито кеглей: {knocked}"
    elif bowling_mode == "strike":
        win = knocked == 10
        win_text = f"Сбито кеглей: {knocked}"
    else:
        win = False
        win_text = ""
    
    if win:
        win_amount = bet * coeff
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute("UPDATE users SET balance = balance + $1, total_bet = total_bet + $2 WHERE id = $3", 
                          int(win_amount * 100), int(bet * 100), message.from_user.id)
        await conn.close()
        
        result_text = "🎉 <b>Победа. Поздравляем!</b>"
        win_block = f"\n\n<blockquote>Начислено: {win_amount} USDT</blockquote>"
        photo = FSInputFile("IMG_0770.jpeg")
        quote = random.choice(win_quotes)
        await log_action(message.from_user.id, "bowling_win", f"Выигрыш {win_amount}$ (ставка {bet}$, режим {mode_text}, кегли {knocked})")
    else:
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute("UPDATE users SET total_bet = total_bet + $1 WHERE id = $2", int(bet * 100), message.from_user.id)
        await conn.close()
        
        result_text = "🚫 <b>Поражение. Повезет в следующий раз!</b>"
        win_block = ""
        photo = FSInputFile("IMG_0769.jpeg")
        quote = random.choice(lose_quotes)
        await log_action(message.from_user.id, "bowling_lose", f"Проигрыш {bet}$ (режим {mode_text}, кегли {knocked})")
    
    result_message = (
        f"{result_text}\n\n"
        f"<blockquote>{win_text}</blockquote>\n"
        f"<blockquote>Коэффициент: {coeff}x</blockquote>\n"
        f"{win_block}\n"
        f"<blockquote>{quote}</blockquote>"
    )
    
    await bowling_msg.reply_photo(
        photo=photo,
        caption=result_message,
        parse_mode=ParseMode.HTML,
        reply_markup=get_make_bet_inline()
    )
    await state.clear()

@dp.message(GameStates.waiting_for_darts_bet)
async def process_darts_bet(message: Message, state: FSMContext):
    try:
        bet = float(message.text.replace(",", "."))
        if bet < 0.30:
            await message.answer("❌ Минимальная ставка 0.30 USDT")
            return
    except:
        await message.answer("❌ Введите число")
        return
    
    data = await state.get_data()
    coeff = data.get("coeff")
    mode_text = data.get("mode_text")
    win_condition = data.get("win_condition")
    
    conn = await asyncpg.connect(DATABASE_URL)
    user = await conn.fetchrow("SELECT * FROM users WHERE id = $1", message.from_user.id)
    
    if user["balance"] < int(bet * 100):
        await conn.close()
        await message.answer("❌ Недостаточно средств")
        await state.clear()
        return
    
    await conn.execute("UPDATE users SET balance = balance - $1 WHERE id = $2", int(bet * 100), message.from_user.id)
    await conn.close()
    
    darts_msg = await message.reply_dice(emoji="🎯")
    await asyncio.sleep(2)
    value = darts_msg.dice.value
    
    win = value in win_condition
    
    if win:
        win_amount = bet * coeff
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute("UPDATE users SET balance = balance + $1, total_bet = total_bet + $2 WHERE id = $3", 
                          int(win_amount * 100), int(bet * 100), message.from_user.id)
        await conn.close()
        
        result_text = "🎉 <b>Победа. Поздравляем!</b>"
        win_block = f"\n\n<blockquote>Начислено: {win_amount} USDT</blockquote>"
        photo = FSInputFile("IMG_0770.jpeg")
        quote = random.choice(win_quotes)
        await log_action(message.from_user.id, "darts_win", f"Выигрыш {win_amount}$ (ставка {bet}$, режим {mode_text}, значение {value})")
    else:
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute("UPDATE users SET total_bet = total_bet + $1 WHERE id = $2", int(bet * 100), message.from_user.id)
        await conn.close()
        
        result_text = "🚫 <b>Поражение. Повезет в следующий раз!</b>"
        win_block = ""
        photo = FSInputFile("IMG_0769.jpeg")
        quote = random.choice(lose_quotes)
        await log_action(message.from_user.id, "darts_lose", f"Проигрыш {bet}$ (режим {mode_text}, значение {value})")
    
    result_message = (
        f"{result_text}\n\n"
        f"<blockquote>Попадание: {value}</blockquote>\n"
        f"<blockquote>Коэффициент: {coeff}x</blockquote>\n"
        f"{win_block}\n"
        f"<blockquote>{quote}</blockquote>"
    )
    
    await darts_msg.reply_photo(
        photo=photo,
        caption=result_message,
        parse_mode=ParseMode.HTML,
        reply_markup=get_make_bet_inline()
    )
    await state.clear()

async def show_bet_request(message, user_id, state, mode_name, coeff):
    conn = await asyncpg.connect(DATABASE_URL)
    user = await conn.fetchrow("SELECT balance FROM users WHERE id = $1", user_id)
    await conn.close()
    
    bet_text = (
        f"<b>💳 Введите сумму для ставки:</b>\n"
        f"└ Текущий баланс: {user['balance']/100}$\n\n"
        f"<blockquote>Коэффициент: {coeff}x</blockquote>\n"
        f"• Минимальная сумма ставки 0.30 USDT"
    )
    
    photo = FSInputFile("IMG_0754.jpeg")
    await message.edit_media(
        types.InputMediaPhoto(
            media=photo,
            caption=bet_text,
            parse_mode=ParseMode.HTML
        ),
        reply_markup=get_bet_cancel_inline()
    )
    await state.set_state(GameStates.waiting_for_bet)

@dp.message(GameStates.waiting_for_bet)
async def process_bet(message: Message, state: FSMContext):
    try:
        bet = float(message.text.replace(",", "."))
        if bet < 0.30:
            await message.answer("❌ Минимальная ставка 0.30 USDT")
            return
    except:
        await message.answer("❌ Введите число")
        return
    
    data = await state.get_data()
    game_mode = data.get("game_mode")
    coeff = data.get("coeff", 1.85)
    sector = data.get("sector")
    
    conn = await asyncpg.connect(DATABASE_URL)
    user = await conn.fetchrow("SELECT * FROM users WHERE id = $1", message.from_user.id)
    
    if user["balance"] < int(bet * 100):
        await conn.close()
        await message.answer("❌ Недостаточно средств")
        await state.clear()
        return
    
    await conn.execute("UPDATE users SET balance = balance - $1 WHERE id = $2", int(bet * 100), message.from_user.id)
    await conn.close()
    
    dice_msg = await message.reply_dice(emoji="🎲")
    await asyncio.sleep(2)
    dice_value = dice_msg.dice.value
    
    if game_mode == "even":
        win = dice_value % 2 == 0
        mode_text = "Четное"
    elif game_mode == "odd":
        win = dice_value % 2 == 1
        mode_text = "Нечетное"
    elif game_mode == "sector":
        win = dice_value == sector
        mode_text = f"Сектор {sector}"
    elif game_mode == "over":
        win = dice_value >= 4
        mode_text = "Больше 3"
    elif game_mode == "under":
        win = dice_value <= 3
        mode_text = "Меньше 4"
    else:
        win = False
        mode_text = "Неизвестно"
    
    if win:
        win_amount = bet * coeff
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute("UPDATE users SET balance = balance + $1, total_bet = total_bet + $2 WHERE id = $3", 
                          int(win_amount * 100), int(bet * 100), message.from_user.id)
        await conn.close()
        
        result_text = "🎉 <b>Победа. Поздравляем!</b>"
        win_text = f"\n\n<blockquote>Начислено: {win_amount} USDT</blockquote>"
        photo = FSInputFile("IMG_0770.jpeg")
        quote = random.choice(win_quotes)
        await log_action(message.from_user.id, "dice_win", f"Выигрыш {win_amount}$ (ставка {bet}$, режим {mode_text}, значение {dice_value})")
    else:
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute("UPDATE users SET total_bet = total_bet + $1 WHERE id = $2", int(bet * 100), message.from_user.id)
        await conn.close()
        
        result_text = "🚫 <b>Поражение. Повезет в следующий раз!</b>"
        win_text = ""
        photo = FSInputFile("IMG_0769.jpeg")
        quote = random.choice(lose_quotes)
        await log_action(message.from_user.id, "dice_lose", f"Проигрыш {bet}$ (режим {mode_text}, значение {dice_value})")
    
    result_message = (
        f"{result_text}\n\n"
        f"<blockquote>Выпало значение: {dice_value}</blockquote>\n"
        f"<blockquote>Коэффициент: {coeff}x</blockquote>\n"
        f"{win_text}\n"
        f"<blockquote>{quote}</blockquote>"
    )
    
    await dice_msg.reply_photo(
        photo=photo,
        caption=result_message,
        parse_mode=ParseMode.HTML,
        reply_markup=get_make_bet_inline()
    )
    await state.clear()

@rate_limit(limit=10)
@dp.callback_query(F.data == "make_bet")
async def make_bet(callback: types.CallbackQuery):
    conn = await asyncpg.connect(DATABASE_URL)
    user = await conn.fetchrow("SELECT * FROM users WHERE id = $1", callback.from_user.id)
    await conn.close()
    
    if user["balance"] < 30:
        await callback.answer("💳 Минимальная ставка 0.30 USDT, пополните баланс", show_alert=True)
        return
    
    photo = FSInputFile("IMG_0754.jpeg")
    await callback.message.edit_media(
        types.InputMediaPhoto(
            media=photo,
            caption="<b>🎉 Раздел доступных режимов</b>\n└ Выберите игру:",
            parse_mode=ParseMode.HTML
        ),
        reply_markup=get_games_menu()
    )
    await callback.answer()

@rate_limit(limit=10)
@dp.callback_query(F.data == "cancel_bet")
async def cancel_bet(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    conn = await asyncpg.connect(DATABASE_URL)
    user = await conn.fetchrow("SELECT * FROM users WHERE id = $1", callback.from_user.id)
    await conn.close()
    
    rank_name, next_threshold = get_rank(user["total_bet"])
    remaining = max(0, next_threshold - user["total_bet"])
    reg_date = user["registered_at"].strftime("%d.%m.%Y")
    
    profile_text = (
        f"<b>🔐 Ваш профиль</b>\n"
        f"└ Текущий баланс: {user['balance']/100}$\n\n"
        f"<blockquote>Зарегистрирован: {reg_date}</blockquote>\n"
        f"<b>Ваш ранг: {rank_name}</b>\n"
        f" ├ Оборот: {user['total_bet']/100}$\n"
        f" └ Осталось: {remaining/100}$ из {next_threshold/100}$"
    )
    
    photo = FSInputFile("IMG_0760.jpeg")
    await callback.message.edit_media(
        types.InputMediaPhoto(
            media=photo,
            caption=profile_text,
            parse_mode=ParseMode.HTML
        ),
        reply_markup=get_profile_inline()
    )
    await callback.answer()

@dp.callback_query(F.data == "deposit")
async def deposit_methods(callback: types.CallbackQuery):
    await log_action(callback.from_user.id, "deposit", "Открыто меню пополнения")
    
    deposit_text = (
        f"<b>💳 Пополнение депозита</b>\n"
        f"└ Выберите удобный для вас способ оплаты:"
    )
    
    photo = FSInputFile("IMG_0757.jpeg")
    await callback.message.edit_media(
        types.InputMediaPhoto(
            media=photo,
            caption=deposit_text,
            parse_mode=ParseMode.HTML
        ),
        reply_markup=get_deposit_methods_inline()
    )
    await callback.answer()

@dp.callback_query(F.data == "withdraw")
async def withdraw_start(callback: types.CallbackQuery, state: FSMContext):
    await log_action(callback.from_user.id, "withdraw", "Начало вывода средств")
    
    withdraw_text = (
        f"<b>🎉 Вывод средств</b>\n"
        f"└ Введите сумму для вывода (мин. 1 USDT):"
    )
    
    photo = FSInputFile("IMG_0764.jpeg")
    await callback.message.edit_media(
        types.InputMediaPhoto(
            media=photo,
            caption=withdraw_text,
            parse_mode=ParseMode.HTML
        ),
        reply_markup=get_cancel_withdraw_inline()
    )
    await state.set_state(WithdrawStates.waiting_for_amount)
    await callback.answer()

@dp.message(WithdrawStates.waiting_for_amount)
async def process_withdraw_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", "."))
        if amount < 1:
            await message.answer("❌ Минимальная сумма вывода: 1 USDT")
            return
    except:
        await message.answer("❌ Введите число")
        return
    
    conn = await asyncpg.connect(DATABASE_URL)
    user = await conn.fetchrow("SELECT * FROM users WHERE id = $1", message.from_user.id)
    
    if not user or user["balance"] < int(amount * 100):
        await conn.close()
        await message.answer("❌ Недостаточно средств")
        await state.clear()
        return
    
    await conn.execute("UPDATE users SET balance = balance - $1 WHERE id = $2", int(amount * 100), message.from_user.id)
    
    result = await conn.fetchrow("""
        INSERT INTO withdraw_requests (user_id, amount) VALUES ($1, $2) RETURNING id
    """, message.from_user.id, int(amount * 100))
    request_id = result["id"]
    
    await conn.close()
    
    await log_action(message.from_user.id, "withdraw_request", f"Создана заявка #{request_id} на сумму {amount} USDT")
    
    await message.answer(
        "<b>💳 Заявка на вывод отправлена администрации, ожидайте!</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=get_profile_only_inline()
    )
    
    username = f"@{message.from_user.username}" if message.from_user.username else f"ID:{message.from_user.id}"
    
    await bot.send_message(
        ADMIN_ID,
        f"<b>🎉 Новая заявка на вывод от пользователя {username} (ID: {message.from_user.id}) на сумму {amount} USDT!</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=get_withdraw_request_inline(request_id, message.from_user.id)
    )
    
    await state.clear()

@dp.callback_query(F.data.startswith("admin_logs_"))
async def admin_logs(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("🚫 Нет доступа", show_alert=True)
        return
    
    user_id = int(callback.data.split("_")[2])
    
    conn = await asyncpg.connect(DATABASE_URL)
    logs = await conn.fetch("""
        SELECT action, details, created_at FROM logs 
        WHERE user_id = $1 
        ORDER BY created_at DESC LIMIT 100
    """, user_id)
    await conn.close()
    
    log_text = f"Логи пользователя ID:{user_id}\n\n"
    for log in logs:
        log_text += f"[{log['created_at'].strftime('%d.%m.%Y %H:%M:%S')}] {log['action']}"
        if log['details']:
            log_text += f" - {log['details']}"
        log_text += "\n"
    
    if not logs:
        log_text = "Нет логов для этого пользователя"
    
    await callback.message.answer_document(
        types.BufferedInputFile(
            log_text.encode('utf-8'),
            filename=f"user_{user_id}_logs.txt"
        ),
        caption=f"📋 Логи пользователя ID:{user_id}"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_approve_"))
async def admin_approve(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("🚫 Нет доступа", show_alert=True)
        return
    
    request_id = int(callback.data.split("_")[2])
    
    conn = await asyncpg.connect(DATABASE_URL)
    request = await conn.fetchrow("SELECT * FROM withdraw_requests WHERE id = $1 AND status = 'pending'", request_id)
    
    if not request:
        await conn.close()
        await callback.answer("Заявка уже обработана", show_alert=True)
        return
    
    await conn.execute("""
        UPDATE withdraw_requests SET status = 'approved', processed_at = CURRENT_TIMESTAMP WHERE id = $1
    """, request_id)
    
    await conn.close()
    
    await log_action(request["user_id"], "withdraw_approved", f"Заявка #{request_id} на сумму {request['amount']/100} USDT одобрена")
    
    async with aiohttp.ClientSession() as session:
        headers = {
            "Crypto-Pay-API-Token": CRYPTO_TOKEN,
            "Content-Type": "application/json"
        }
        data = {
            "asset": "USDT",
            "amount": str(request["amount"] / 100),
            "description": f"Вывод средств для {request['user_id']}"
        }
        
        async with session.post("https://testnet-pay.crypt.bot/api/createCheck", json=data, headers=headers) as resp:
            result = await resp.json()
            
            if result.get("ok"):
                check = result["result"]
                
                await bot.send_message(
                    request["user_id"],
                    f"🎉 Чек создан!\n\n"
                    f"Сумма: {request['amount']/100} USDT\n"
                    f"Ссылка: {check['bot_check_url']}\n\n"
                    f"Перейдите по ссылке и активируйте чек для получения средств"
                )
                
                await callback.message.edit_text(
                    f"✅ Заявка #{request_id} подтверждена, чек отправлен пользователю",
                    reply_markup=None
                )
                await callback.answer("Чек отправлен")
            else:
                await callback.message.answer(f"❌ Ошибка создания чека: {result}")
                await callback.answer("Ошибка")

@dp.callback_query(F.data.startswith("admin_reject_"))
async def admin_reject(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("🚫 Нет доступа", show_alert=True)
        return
    
    request_id = int(callback.data.split("_")[2])
    
    conn = await asyncpg.connect(DATABASE_URL)
    request = await conn.fetchrow("SELECT * FROM withdraw_requests WHERE id = $1 AND status = 'pending'", request_id)
    
    if not request:
        await conn.close()
        await callback.answer("Заявка уже обработана", show_alert=True)
        return
    
    await conn.execute("""
        UPDATE withdraw_requests SET status = 'rejected', processed_at = CURRENT_TIMESTAMP WHERE id = $1
    """, request_id)
    
    await conn.execute("UPDATE users SET balance = balance + $1 WHERE id = $2", request["amount"], request["user_id"])
    
    await conn.close()
    
    await log_action(request["user_id"], "withdraw_rejected", f"Заявка #{request_id} на сумму {request['amount']/100} USDT отклонена")
    
    await bot.send_message(
        request["user_id"],
        "<b>😔 Ваша заявка на вывод была отклонена, свяжитесь со службой поддержки.</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=get_profile_only_inline()
    )
    
    await callback.message.edit_text(
        f"❌ Заявка #{request_id} отклонена, средства возвращены пользователю",
        reply_markup=None
    )
    await callback.answer("Заявка отклонена")

@dp.callback_query(F.data == "crypto_bot")
async def crypto_bot_deposit(callback: types.CallbackQuery, state: FSMContext):
    await log_action(callback.from_user.id, "deposit_crypto", "Выбран способ CryptoBot")
    
    amount_text = (
        f"<b>💳 Пополнение депозита</b>\n"
        f"└ Введите сумму для оплаты:"
    )
    
    photo = FSInputFile("IMG_0757.jpeg")
    await callback.message.edit_media(
        types.InputMediaPhoto(
            media=photo,
            caption=amount_text,
            parse_mode=ParseMode.HTML
        ),
        reply_markup=get_cancel_inline()
    )
    await state.set_state(DepositStates.waiting_for_amount)
    await callback.answer()

@dp.message(DepositStates.waiting_for_amount)
async def process_deposit_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", "."))
        if amount <= 0:
            await message.answer("❌ Сумма должна быть больше 0")
            return
    except:
        await message.answer("❌ Введите число")
        return
    
    await log_action(message.from_user.id, "deposit_request", f"Создание инвойса на {amount} USDT")
    
    async with aiohttp.ClientSession() as session:
        headers = {
            "Crypto-Pay-API-Token": CRYPTO_TOKEN,
            "Content-Type": "application/json"
        }
        data = {
            "asset": "USDT",
            "amount": str(amount),
            "description": f"Пополнение баланса для {message.from_user.id}"
        }
        
        async with session.post("https://testnet-pay.crypt.bot/api/createInvoice", json=data, headers=headers) as resp:
            result = await resp.json()
            
            if result.get("ok"):
                invoice = result["result"]
                msg = await message.answer(
                    f"💳 Оплатите счет:\n{invoice['pay_url']}\n\n"
                    f"Сумма: {amount} USDT\n"
                    f"После оплаты баланс пополнится автоматически"
                )
                
                user_invoice_messages[invoice["invoice_id"]] = {
                    "user_id": message.from_user.id,
                    "message_id": msg.message_id,
                    "chat_id": message.chat.id,
                    "amount": int(amount * 100)
                }
                
                await state.clear()
                
                asyncio.create_task(check_payment(invoice["invoice_id"]))
            else:
                await message.answer("❌ Ошибка создания счета. Попробуйте позже.")
                await state.clear()

async def check_payment(invoice_id):
    await asyncio.sleep(3)
    
    for _ in range(30):
        await asyncio.sleep(2)
        
        async with aiohttp.ClientSession() as session:
            headers = {
                "Crypto-Pay-API-Token": CRYPTO_TOKEN
            }
            params = {"invoice_ids": invoice_id}
            
            async with session.get("https://testnet-pay.crypt.bot/api/getInvoices", params=params, headers=headers) as resp:
                result = await resp.json()
                
                if result.get("ok") and result["result"]["items"]:
                    invoice = result["result"]["items"][0]
                    if invoice["status"] == "paid":
                        invoice_data = user_invoice_messages.get(invoice_id)
                        if invoice_data:
                            user_id = invoice_data["user_id"]
                            amount = invoice_data["amount"]
                            chat_id = invoice_data["chat_id"]
                            message_id = invoice_data["message_id"]
                            
                            try:
                                await bot.delete_message(chat_id, message_id)
                            except:
                                pass
                            
                            conn = await asyncpg.connect(DATABASE_URL)
                            await conn.execute("UPDATE users SET balance = balance + $1 WHERE id = $2", amount, user_id)
                            await conn.close()
                            
                            await log_action(user_id, "deposit_success", f"Пополнение на {amount/100} USDT")
                            
                            await bot.send_message(
                                user_id,
                                "🎉"
                            )
                            
                            await bot.send_message(
                                user_id,
                                f"<b>💎 Успешное пополнение</b>\n└ На ваш баланс зачислено {amount/100} USDT",
                                parse_mode=ParseMode.HTML,
                                reply_markup=get_make_bet_inline()
                            )
                            
                            del user_invoice_messages[invoice_id]
                        return
                    elif invoice["status"] == "expired":
                        invoice_data = user_invoice_messages.get(invoice_id)
                        if invoice_data:
                            await bot.send_message(invoice_data["user_id"], "❌ Счет просрочен. Попробуйте снова.")
                            del user_invoice_messages[invoice_id]
                        return

@dp.callback_query(F.data == "cancel_deposit")
async def cancel_deposit(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await log_action(callback.from_user.id, "deposit_cancel", "Отмена пополнения")
    
    conn = await asyncpg.connect(DATABASE_URL)
    user = await conn.fetchrow("SELECT * FROM users WHERE id = $1", callback.from_user.id)
    await conn.close()
    
    if not user:
        await callback.message.answer("Ошибка. Напишите /start")
        await callback.answer()
        return
    
    rank_name, next_threshold = get_rank(user["total_bet"])
    remaining = max(0, next_threshold - user["total_bet"])
    reg_date = user["registered_at"].strftime("%d.%m.%Y")
    
    profile_text = (
        f"<b>🔐 Ваш профиль</b>\n"
        f"└ Текущий баланс: {user['balance']/100}$\n\n"
        f"<blockquote>Зарегистрирован: {reg_date}</blockquote>\n"
        f"<b>Ваш ранг: {rank_name}</b>\n"
        f" ├ Оборот: {user['total_bet']/100}$\n"
        f" └ Осталось: {remaining/100}$ из {next_threshold/100}$"
    )
    
    photo = FSInputFile("IMG_0760.jpeg")
    await callback.message.edit_media(
        types.InputMediaPhoto(
            media=photo,
            caption=profile_text,
            parse_mode=ParseMode.HTML
        ),
        reply_markup=get_profile_inline()
    )
    await callback.answer()

@dp.callback_query(F.data == "cancel_withdraw")
async def cancel_withdraw(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await log_action(callback.from_user.id, "withdraw_cancel", "Отмена вывода")
    
    conn = await asyncpg.connect(DATABASE_URL)
    user = await conn.fetchrow("SELECT * FROM users WHERE id = $1", callback.from_user.id)
    await conn.close()
    
    if not user:
        await callback.message.answer("Ошибка. Напишите /start")
        await callback.answer()
        return
    
    rank_name, next_threshold = get_rank(user["total_bet"])
    remaining = max(0, next_threshold - user["total_bet"])
    reg_date = user["registered_at"].strftime("%d.%m.%Y")
    
    profile_text = (
        f"<b>🔐 Ваш профиль</b>\n"
        f"└ Текущий баланс: {user['balance']/100}$\n\n"
        f"<blockquote>Зарегистрирован: {reg_date}</blockquote>\n"
        f"<b>Ваш ранг: {rank_name}</b>\n"
        f" ├ Оборот: {user['total_bet']/100}$\n"
        f" └ Осталось: {remaining/100}$ из {next_threshold/100}$"
    )
    
    photo = FSInputFile("IMG_0760.jpeg")
    await callback.message.edit_media(
        types.InputMediaPhoto(
            media=photo,
            caption=profile_text,
            parse_mode=ParseMode.HTML
        ),
        reply_markup=get_profile_inline()
    )
    await callback.answer()

@dp.callback_query(F.data == "referral")
async def referral_program(callback: types.CallbackQuery):
    await log_action(callback.from_user.id, "referral", "Просмотр реферальной программы")
    
    conn = await asyncpg.connect(DATABASE_URL)
    
    referrals = await conn.fetch("SELECT * FROM users WHERE referrer_id = $1", callback.from_user.id)
    invited = len(referrals)
    
    active = 0
    for ref in referrals:
        if ref["total_bet"] > 0:
            active += 1
    
    user = await conn.fetchrow("SELECT referral_earnings FROM users WHERE id = $1", callback.from_user.id)
    await conn.close()
    
    bot_username = (await bot.get_me()).username
    referral_link = f"https://t.me/{bot_username}?start={callback.from_user.id}"
    
    referral_text = (
        f"<b>🧩 Реферальная программа</b>\n\n"
        f"<b>💳 Процент от проигрышей реферала:</b>\n"
        f"<blockquote>• 5% от каждого реферала</blockquote>\n\n"
        f"<b>👾 Ваша статистика:</b>\n"
        f"├ Приглашено: {invited} чел.\n"
        f"├ Активных: {active} чел.\n"
        f"└ Заработано: {user['referral_earnings']/100:.2f}$\n\n"
        f"<b>🎉 Ваша ссылка:</b>\n"
        f"{referral_link}"
    )
    
    photo = FSInputFile("IMG_0763.jpeg")
    await callback.message.edit_media(
        types.InputMediaPhoto(
            media=photo,
            caption=referral_text,
            parse_mode=ParseMode.HTML
        ),
        reply_markup=get_referral_inline()
    )
    await callback.answer()

@dp.callback_query(F.data == "back_to_profile")
async def back_to_profile(callback: types.CallbackQuery):
    conn = await asyncpg.connect(DATABASE_URL)
    user = await conn.fetchrow("SELECT * FROM users WHERE id = $1", callback.from_user.id)
    await conn.close()
    
    rank_name, next_threshold = get_rank(user["total_bet"])
    remaining = max(0, next_threshold - user["total_bet"])
    reg_date = user["registered_at"].strftime("%d.%m.%Y")
    
    profile_text = (
        f"<b>🔐 Ваш профиль</b>\n"
        f"└ Текущий баланс: {user['balance']/100}$\n\n"
        f"<blockquote>Зарегистрирован: {reg_date}</blockquote>\n"
        f"<b>Ваш ранг: {rank_name}</b>\n"
        f" ├ Оборот: {user['total_bet']/100}$\n"
        f" └ Осталось: {remaining/100}$ из {next_threshold/100}$"
    )
    
    photo = FSInputFile("IMG_0760.jpeg")
    await callback.message.edit_media(
        types.InputMediaPhoto(
            media=photo,
            caption=profile_text,
            parse_mode=ParseMode.HTML
        ),
        reply_markup=get_profile_inline()
    )
    await callback.answer()

@dp.message(Command("post"))
async def broadcast_start(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await message.answer("🚫 Нет доступа")
        return
    
    await message.answer("📢 Отправьте сообщение для рассылки (текст, фото, видео и т.д.)")
    await state.set_state(BroadcastStates.waiting_for_message)

@dp.message(BroadcastStates.waiting_for_message)
async def broadcast_send(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await state.clear()
        return
    
    conn = await asyncpg.connect(DATABASE_URL)
    users = await conn.fetch("SELECT id FROM users")
    await conn.close()
    
    success = 0
    fail = 0
    
    await message.answer(f"📢 Начинаю рассылку для {len(users)} пользователей...")
    
    for user in users:
        try:
            if message.text:
                await bot.send_message(user["id"], message.text, parse_mode=ParseMode.HTML)
            elif message.photo:
                await bot.send_photo(user["id"], message.photo[-1].file_id, caption=message.caption, parse_mode=ParseMode.HTML)
            elif message.video:
                await bot.send_video(user["id"], message.video.file_id, caption=message.caption, parse_mode=ParseMode.HTML)
            elif message.document:
                await bot.send_document(user["id"], message.document.file_id, caption=message.caption, parse_mode=ParseMode.HTML)
            success += 1
        except:
            fail += 1
        await asyncio.sleep(0.05)
    
    await message.answer(f"✅ Рассылка завершена\n✅ Успешно: {success}\n❌ Ошибок: {fail}")
    await state.clear()

# ==================== ТОП ИГРОКОВ (АДМИН) ====================

@dp.message(Command("top"))
async def top_all_time(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    conn = await asyncpg.connect(DATABASE_URL)
    
    query = """
        SELECT id, username, total_bet 
        FROM users 
        WHERE total_bet > 0
        ORDER BY total_bet DESC 
        LIMIT 10
    """
    
    top_users = await conn.fetch(query)
    total_turnover = await conn.fetchval("SELECT SUM(total_bet) FROM users") or 0
    await conn.close()
    
    medals = ["🥇", "🥈", "🥉", "🏅", "🏅", "🏅", "🏅", "🏅", "🏅", "🏅"]
    
    top_text = f"<b>🤑 Топ игроков всё время:</b>\n\n"
    
    for i, user in enumerate(top_users):
        user_id = user["id"]
        total_bet = user["total_bet"] / 100
        username = user["username"] if user["username"] else f"ID:{user_id}"
        medal = medals[i] if i < len(medals) else "🏅"
        
        top_text += f"{medal} <b><a href=\"https://t.me/Hot_dicebot?start=user_{user_id}\">{username}</a></b> - <b>{total_bet:.2f}$</b>\n"
    
    top_text += f"\n<b>💸 Оборот всё время: {total_turnover/100:.2f}$</b>"
    
    await message.answer(top_text, parse_mode=ParseMode.HTML)

@dp.message(Command("topd"))
async def top_day(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    conn = await asyncpg.connect(DATABASE_URL)
    
    today = datetime.now().date()
    
    query = """
        SELECT user_id, SUM(amount) as total 
        FROM withdraw_requests 
        WHERE status = 'approved' AND processed_at::date = $1
        GROUP BY user_id 
        ORDER BY total DESC 
        LIMIT 10
    """
    
    top_users = await conn.fetch(query, today)
    total_turnover = await conn.fetchval("SELECT SUM(amount) FROM withdraw_requests WHERE status = 'approved' AND processed_at::date = $1", today) or 0
    await conn.close()
    
    medals = ["🥇", "🥈", "🥉", "🏅", "🏅", "🏅", "🏅", "🏅", "🏅", "🏅"]
    
    top_text = f"<b>🤑 Топ игроков сегодня:</b>\n\n"
    
    for i, user in enumerate(top_users):
        user_id = user["user_id"]
        total = user["total"] / 100
        
        conn2 = await asyncpg.connect(DATABASE_URL)
        username = await conn2.fetchval("SELECT username FROM users WHERE id = $1", user_id)
        await conn2.close()
        
        display_name = username if username else f"ID:{user_id}"
        medal = medals[i] if i < len(medals) else "🏅"
        
        top_text += f"{medal} <b><a href=\"https://t.me/Hot_dicebot?start=user_{user_id}\">{display_name}</a></b> - <b>{total:.2f}$</b>\n"
    
    top_text += f"\n<b>💸 Оборот сегодня: {total_turnover/100:.2f}$</b>"
    
    await message.answer(top_text, parse_mode=ParseMode.HTML)

@dp.message(Command("topw"))
async def top_week(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    conn = await asyncpg.connect(DATABASE_URL)
    
    week_ago = datetime.now() - timedelta(days=7)
    
    query = """
        SELECT user_id, SUM(amount) as total 
        FROM withdraw_requests 
        WHERE status = 'approved' AND processed_at >= $1
        GROUP BY user_id 
        ORDER BY total DESC 
        LIMIT 10
    """
    
    top_users = await conn.fetch(query, week_ago)
    total_turnover = await conn.fetchval("SELECT SUM(amount) FROM withdraw_requests WHERE status = 'approved' AND processed_at >= $1", week_ago) or 0
    await conn.close()
    
    medals = ["🥇", "🥈", "🥉", "🏅", "🏅", "🏅", "🏅", "🏅", "🏅", "🏅"]
    
    top_text = f"<b>🤑 Топ игроков за неделю:</b>\n\n"
    
    for i, user in enumerate(top_users):
        user_id = user["user_id"]
        total = user["total"] / 100
        
        conn2 = await asyncpg.connect(DATABASE_URL)
        username = await conn2.fetchval("SELECT username FROM users WHERE id = $1", user_id)
        await conn2.close()
        
        display_name = username if username else f"ID:{user_id}"
        medal = medals[i] if i < len(medals) else "🏅"
        
        top_text += f"{medal} <b><a href=\"https://t.me/Hot_dicebot?start=user_{user_id}\">{display_name}</a></b> - <b>{total:.2f}$</b>\n"
    
    top_text += f"\n<b>💸 Оборот за неделю: {total_turnover/100:.2f}$</b>"
    
    await message.answer(top_text, parse_mode=ParseMode.HTML)

@dp.message(Command("topm"))
async def top_month(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    conn = await asyncpg.connect(DATABASE_URL)
    
    month_ago = datetime.now() - timedelta(days=30)
    
    query = """
        SELECT user_id, SUM(amount) as total 
        FROM withdraw_requests 
        WHERE status = 'approved' AND processed_at >= $1
        GROUP BY user_id 
        ORDER BY total DESC 
        LIMIT 10
    """
    
    top_users = await conn.fetch(query, month_ago)
    total_turnover = await conn.fetchval("SELECT SUM(amount) FROM withdraw_requests WHERE status = 'approved' AND processed_at >= $1", month_ago) or 0
    await conn.close()
    
    medals = ["🥇", "🥈", "🥉", "🏅", "🏅", "🏅", "🏅", "🏅", "🏅", "🏅"]
    
    top_text = f"<b>🤑 Топ игроков за месяц:</b>\n\n"
    
    for i, user in enumerate(top_users):
        user_id = user["user_id"]
        total = user["total"] / 100
        
        conn2 = await asyncpg.connect(DATABASE_URL)
        username = await conn2.fetchval("SELECT username FROM users WHERE id = $1", user_id)
        await conn2.close()
        
        display_name = username if username else f"ID:{user_id}"
        medal = medals[i] if i < len(medals) else "🏅"
        
        top_text += f"{medal} <b><a href=\"https://t.me/Hot_dicebot?start=user_{user_id}\">{display_name}</a></b> - <b>{total:.2f}$</b>\n"
    
    top_text += f"\n<b>💸 Оборот за месяц: {total_turnover/100:.2f}$</b>"
    
    await message.answer(top_text, parse_mode=ParseMode.HTML)

@dp.callback_query()
async def handle_callbacks(callback: types.CallbackQuery):
    await callback.answer("🚧 В разработке", show_alert=True)

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
