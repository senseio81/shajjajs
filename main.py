import asyncio
import logging
import os
import aiohttp
import random
from datetime import datetime
from io import StringIO
from collections import defaultdict
import time

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.enums import ParseMode, ContentType
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
import asyncpg

TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
CRYPTO_TOKEN = os.getenv("CRYPTO_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

user_invoice_messages = {}
rate_limit_dict = defaultdict(list)
user_dice_data = {}

casino_quotes = [
    "Удача любит смелых!",
    "Казино всегда выигрывает... но не сегодня!",
    "Веришь в удачу?",
    "Фортуна улыбнулась тебе!",
    "В следующий раз повезёт больше!",
    "Азарт — это наше всё!",
    "Сегодня твой день!",
    "Главное — не останавливаться!"
]

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
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute("""
            INSERT INTO logs (user_id, action, details) VALUES ($1, $2, $3)
        """, user_id, action, details)
        await conn.close()
    except Exception as e:
        logger.error(f"Log action error: {e}")

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
                InlineKeyboardButton(text="🛩️ Самолетик", callback_data="game_plane"),
                InlineKeyboardButton(text="🎳 Боулинг", callback_data="game_bowling")
            ],
            [InlineKeyboardButton(text="« Назад", callback_data="back_to_profile")]
        ]
    )

def get_dice_modes():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🎲 Четное", callback_data="dice_even"),
                InlineKeyboardButton(text="🎲 Нечетное", callback_data="dice_odd")
            ],
            [
                InlineKeyboardButton(text="🎲 Сектора", callback_data="dice_sector"),
                InlineKeyboardButton(text="🎲 Больше/Меньше", callback_data="dice_overunder")
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

@dp.message(Command("start"))
async def start_command(message: Message):
    args = message.text.split()
    referrer_id = None
    if len(args) > 1:
        try:
            referrer_id = int(args[1])
        except:
            pass
    
    conn = await asyncpg.connect(DATABASE_URL)
    
    await conn.execute("""
        INSERT INTO users (id, username, referrer_id) 
        VALUES ($1, $2, $3)
        ON CONFLICT (id) DO NOTHING
    """, message.from_user.id, message.from_user.username, referrer_id)
    
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
async def darts_stub(callback: types.CallbackQuery):
    await callback.answer("🎯 Дартс в разработке", show_alert=True)

@rate_limit(limit=10)
@dp.callback_query(F.data == "game_plane")
async def plane_stub(callback: types.CallbackQuery):
    await callback.answer("🛩️ Самолетик в разработке", show_alert=True)

@rate_limit(limit=10)
@dp.callback_query(F.data == "game_bowling")
async def bowling_stub(callback: types.CallbackQuery):
    await callback.answer("🎳 Боулинг в разработке", show_alert=True)

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

async def show_bet_request(message, user_id, state, mode_name, coeff):
    conn = await asyncpg.connect(DATABASE_URL)
    user = await conn.fetchrow("SELECT balance FROM users WHERE id = $1", user_id)
    await conn.close()
    
    bet_text = (
        f"<b>💳 Введите сумму для ставки:</b>\n"
        f"└ Текущий баланс: {user['balance']/100}$\n\n"
        f"<blockquote>Коэффициент: {coeff}x</blockquote>\n"
        f"<blockquote>Комиссия: 4.5%</blockquote>\n"
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
    logger.info(f"=== process_bet START for user {message.from_user.id} ===")
    
    try:
        bet = float(message.text.replace(",", "."))
        logger.info(f"Bet amount: {bet}")
        if bet < 0.30:
            await message.answer("❌ Минимальная ставка 0.30 USDT")
            return
    except:
        logger.error(f"Invalid bet format: {message.text}")
        await message.answer("❌ Введите число")
        return
    
    data = await state.get_data()
    logger.info(f"Game data from state: {data}")
    
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
    
    # Сохраняем данные для игры (НЕ сохраняем state!)
    user_dice_data[message.from_user.id] = {
        "bet": bet,
        "game_mode": game_mode,
        "coeff": coeff,
        "sector": sector
    }
    
    logger.info(f"Saved dice data for user {message.from_user.id}: {user_dice_data[message.from_user.id]}")
    logger.info("Sending dice...")
    await message.answer_dice(emoji="🎲")
    logger.info("Dice sent, waiting for response...")
    
    # Очищаем состояние, так как игра начата
    await state.clear()

# ИСПРАВЛЕННЫЙ ОБРАБОТЧИК DICE - используем F.dice вместо ContentType.DICE
@dp.message(F.dice)
async def handle_dice(message: Message):
    logger.info("=" * 50)
    logger.info(f"DICE HANDLER TRIGGERED!")
    logger.info(f"User ID: {message.from_user.id}")
    logger.info(f"Dice value: {message.dice.value}")
    logger.info(f"Dice emoji: {message.dice.emoji}")
    logger.info(f"user_dice_data keys: {list(user_dice_data.keys())}")
    
    user_id = message.from_user.id
    
    # Проверяем, есть ли данные для этого пользователя
    if user_id not in user_dice_data:
        logger.warning(f"NO DICE DATA FOUND for user {user_id}")
        logger.warning(f"Available data: {user_dice_data}")
        return
    
    logger.info(f"Found dice data for user {user_id}: {user_dice_data[user_id]}")
    
    # Получаем данные и удаляем их из словаря
    data = user_dice_data.pop(user_id)
    bet = data["bet"]
    game_mode = data["game_mode"]
    coeff = data["coeff"]
    sector = data.get("sector")
    
    dice_value = message.dice.value
    logger.info(f"Processing: mode={game_mode}, bet={bet}, coeff={coeff}, dice={dice_value}")
    
    # Определяем победу в зависимости от режима
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
    
    logger.info(f"Result: win={win}, mode_text={mode_text}")
    
    conn = await asyncpg.connect(DATABASE_URL)
    
    if win:
        win_amount = bet * coeff
        logger.info(f"WIN! Amount: {win_amount}")
        
        await conn.execute(
            "UPDATE users SET balance = balance + $1, total_bet = total_bet + $2 WHERE id = $3", 
            int(win_amount * 100), 
            int(bet * 100), 
            user_id
        )
        
        result_text = "✅ Победа!"
        photo = FSInputFile("IMG_0770.jpeg")
        await log_action(user_id, "dice_win", f"Выигрыш {win_amount}$ (ставка {bet}$, режим {mode_text}, значение {dice_value})")
        logger.info(f"User {user_id} won {win_amount}$")
    else:
        logger.info(f"LOSS! Amount: {bet}")
        
        await conn.execute(
            "UPDATE users SET total_bet = total_bet + $1 WHERE id = $2", 
            int(bet * 100), 
            user_id
        )
        
        # Начисляем бонус рефереру (5% от проигрыша)
        user = await conn.fetchrow("SELECT referrer_id FROM users WHERE id = $1", user_id)
        if user and user["referrer_id"]:
            referrer_bonus = int(bet * 100 * 0.05)
            await conn.execute(
                "UPDATE users SET balance = balance + $1, referral_earnings = referral_earnings + $2 WHERE id = $3", 
                referrer_bonus, 
                referrer_bonus, 
                user["referrer_id"]
            )
            await log_action(user["referrer_id"], "referral_earning", f"Начислено {referrer_bonus/100}$ за проигрыш реферала {user_id}")
        
        result_text = "🚫 Поражение. Попробуй снова!"
        photo = FSInputFile("IMG_0769.jpeg")
        await log_action(user_id, "dice_lose", f"Проигрыш {bet}$ (режим {mode_text}, значение {dice_value})")
        logger.info(f"User {user_id} lost {bet}$")
    
    # Получаем обновленный баланс
    user = await conn.fetchrow("SELECT balance FROM users WHERE id = $1", user_id)
    await conn.close()
    
    quote = random.choice(casino_quotes)
    
    result_message = (
        f"{result_text}\n\n"
        f"<blockquote>Выпало значение: {dice_value}</blockquote>\n"
        f"<blockquote>Коэффициент: {coeff}x</blockquote>\n"
        f"<blockquote>Ваш баланс: {user['balance']/100}$</blockquote>\n"
        f"<blockquote>{quote}</blockquote>"
    )
    
    logger.info(f"Sending result to user {user_id}")
    await message.answer_photo(
        photo=photo,
        caption=result_message,
        parse_mode=ParseMode.HTML,
        reply_markup=get_make_bet_inline()
    )
    
    logger.info(f"DICE HANDLER FINISHED for user {user_id}")
    logger.info("=" * 50)

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
            caption="<b>🎲 Выберите режим игры:</b>",
            parse_mode=ParseMode.HTML
        ),
        reply_markup=get_dice_modes()
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

@dp.callback_query()
async def handle_callbacks(callback: types.CallbackQuery):
    await callback.answer("🚧 В разработке", show_alert=True)

async def main():
    await init_db()
    logger.info("Bot started!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
