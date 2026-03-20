import asyncio
import logging
import os
import aiohttp

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

logging.basicConfig(level=logging.INFO)

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

class DepositStates(StatesGroup):
    waiting_for_amount = State()

async def init_db():
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("DROP TABLE IF EXISTS users")
    await conn.execute("""
        CREATE TABLE users (
            id BIGINT PRIMARY KEY,
            username TEXT,
            balance INTEGER DEFAULT 0,
            total_bet INTEGER DEFAULT 0,
            registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            referrer_id BIGINT,
            referral_earnings INTEGER DEFAULT 0
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_referrer_id ON users(referrer_id)")
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

def get_play_inline():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎲 Сделать ставку", callback_data="play_stub")]
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
    
    user = await conn.fetchrow("SELECT * FROM users WHERE id = $1", message.from_user.id)
    if not user:
        await conn.execute("""
            INSERT INTO users (id, username, referrer_id) VALUES ($1, $2, $3)
        """, message.from_user.id, message.from_user.username, referrer_id)
    
    await conn.close()
    
    await message.answer(
        "<b>🎉 Добро пожаловать в Hot Dice 🎲</b>\n\nПоддержка: @MNGhotdice",
        parse_mode=ParseMode.HTML,
        reply_markup=get_main_keyboard()
    )

@dp.message(F.text == "💳 Профиль")
async def profile_command(message: Message):
    await message.reply("🎲")
    
    conn = await asyncpg.connect(DATABASE_URL)
    user = await conn.fetchrow("SELECT * FROM users WHERE id = $1", message.from_user.id)
    await conn.close()
    
    if not user:
        await message.answer("Ошибка. Напишите /start")
        return
    
    rank_name, next_threshold = get_rank(user["total_bet"])
    remaining = max(0, next_threshold - user["total_bet"])
    reg_date = user["registered_at"].strftime("%d.%m.%Y")
    
    profile_text = (
        f"<b>🔐 Ваш профиль</b>\n"
        f"└ Текущий баланс: {user['balance']}$\n\n"
        f"<blockquote>Зарегистрирован: {reg_date}</blockquote>\n"
        f"<b>Ваш ранг: {rank_name}</b>\n"
        f" ├ Оборот: {user['total_bet']}$\n"
        f" └ Осталось: {remaining}$ из {next_threshold}$"
    )
    
    photo = FSInputFile("IMG_0760.jpeg")
    await message.answer_photo(
        photo=photo,
        caption=profile_text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_profile_inline()
    )

@dp.callback_query(F.data == "deposit")
async def deposit_methods(callback: types.CallbackQuery):
    deposit_text = (
        f"<b>💳 Пополнение депозита</b>\n"
        f"└ Выберите удобный для вас способ оплаты:"
    )
    
    await callback.message.edit_caption(
        caption=deposit_text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_deposit_methods_inline()
    )
    await callback.answer()

@dp.callback_query(F.data == "crypto_bot")
async def crypto_bot_deposit(callback: types.CallbackQuery, state: FSMContext):
    amount_text = (
        f"<b>💳 Пополнение депозита</b>\n"
        f"└ Введите сумму для оплаты:"
    )
    
    await callback.message.edit_caption(
        caption=amount_text,
        parse_mode=ParseMode.HTML,
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
                await message.answer(
                    f"💳 Оплатите счет:\n{invoice['pay_url']}\n\n"
                    f"Сумма: {amount} USDT\n"
                    f"После оплаты баланс пополнится автоматически"
                )
                
                await state.update_data(amount=amount, invoice_id=invoice["invoice_id"])
                await state.clear()
                
                asyncio.create_task(check_payment(invoice["invoice_id"], message.from_user.id, amount))
            else:
                await message.answer("❌ Ошибка создания счета. Попробуйте позже.")
                await state.clear()

async def check_payment(invoice_id, user_id, amount):
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
                        conn = await asyncpg.connect(DATABASE_URL)
                        await conn.execute("UPDATE users SET balance = balance + $1 WHERE id = $2", int(amount), user_id)
                        await conn.close()
                        
                        await bot.send_message(
                            user_id,
                            "🎉"
                        )
                        await bot.send_message(
                            user_id,
                            f"<b>💎 Успешное пополнение</b>\n└ На ваш баланс зачислено {amount} USDT",
                            parse_mode=ParseMode.HTML,
                            reply_markup=get_play_inline()
                        )
                        return
                    elif invoice["status"] == "expired":
                        await bot.send_message(user_id, "❌ Счет просрочен. Попробуйте снова.")
                        return

@dp.message(F.text == "🎲 Играть")
async def play_dummy(message: Message):
    await message.answer("🎲 Игра в разработке 🛠")

@dp.callback_query(F.data == "play_stub")
async def play_stub(callback: types.CallbackQuery):
    await callback.answer("🎲 Игра в разработке", show_alert=True)

@dp.callback_query(F.data == "cancel_deposit")
async def cancel_deposit(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await profile_command(callback.message)
    await callback.answer()

@dp.callback_query(F.data == "referral")
async def referral_program(callback: types.CallbackQuery):
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
        f"└ Заработано: {user['referral_earnings']:.2f}$\n\n"
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
        f"└ Текущий баланс: {user['balance']}$\n\n"
        f"<blockquote>Зарегистрирован: {reg_date}</blockquote>\n"
        f"<b>Ваш ранг: {rank_name}</b>\n"
        f" ├ Оборот: {user['total_bet']}$\n"
        f" └ Осталось: {remaining}$ из {next_threshold}$"
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
