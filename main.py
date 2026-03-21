from aiogram import Bot, Dispatcher, types, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
import asyncio
import os
import random
import time
from collections import defaultdict

TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(token=TOKEN)
dp = Dispatcher()

user_games = {}

def get_plane_buttons():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🟢 ЗАБРАТЬ", callback_data="cashout"),
                InlineKeyboardButton(text="❌ ВЫЙТИ", callback_data="exit")
            ]
        ]
    )

@dp.message(Command("start"))
async def start(message: Message):
    await message.answer("🛩️ Самолетик\nВведи сумму ставки (мин 0.30 USDT):")

@dp.message()
async def place_bet(message: Message):
    try:
        bet = float(message.text.replace(",", "."))
        if bet < 0.30:
            await message.answer("❌ Минимальная ставка 0.30 USDT")
            return
    except:
        await message.answer("❌ Введите число")
        return
    
    crash = random.uniform(1.20, 100.00)
    
    msg = await message.answer(
        f"🛩️ САМОЛЕТИК\n\n"
        f"Текущий коэффициент: 1.00x\n"
        f"Ставка: {bet} USDT\n"
        f"Потенциальный выигрыш: {bet:.2f} USDT",
        reply_markup=get_plane_buttons()
    )
    
    user_games[message.from_user.id] = {
        "bet": bet,
        "crash": crash,
        "multiplier": 1.00,
        "active": True,
        "msg_id": msg.message_id,
        "chat_id": message.chat.id
    }
    
    asyncio.create_task(plane_loop(message.from_user.id))

async def plane_loop(user_id):
    multiplier = 1.00
    step = 0
    
    while user_id in user_games and user_games[user_id]["active"]:
        await asyncio.sleep(0.8)
        
        if user_id not in user_games or not user_games[user_id]["active"]:
            break
        
        increase = random.uniform(0.05, 0.30)
        multiplier += increase
        user_games[user_id]["multiplier"] = multiplier
        
        bet = user_games[user_id]["bet"]
        win = bet * multiplier
        crash = user_games[user_id]["crash"]
        
        try:
            await bot.edit_message_text(
                f"🛩️ САМОЛЕТИК\n\n"
                f"Текущий коэффициент: {multiplier:.2f}x\n"
                f"Ставка: {bet} USDT\n"
                f"Потенциальный выигрыш: {win:.2f} USDT",
                chat_id=user_games[user_id]["chat_id"],
                message_id=user_games[user_id]["msg_id"],
                reply_markup=get_plane_buttons()
            )
        except:
            pass
        
        if multiplier >= crash:
            data = user_games.pop(user_id)
            await bot.send_message(
                data["chat_id"],
                f"💥 САМОЛЕТ УЛЕТЕЛ!\nКоэффициент: {crash:.2f}x\nСтавка: {data['bet']} USDT\nВы проиграли!",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[[InlineKeyboardButton(text="💎 Играть снова", callback_data="play_again")]]
                )
            )
            break

@dp.callback_query(F.data == "cashout")
async def cashout(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    if user_id not in user_games:
        await callback.answer("Игра не найдена", show_alert=True)
        return
    
    data = user_games.pop(user_id)
    win = data["bet"] * data["multiplier"]
    
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        f"✅ ВЫ ВЫИГРАЛИ!\nСтавка: {data['bet']} USDT\nКоэффициент: {data['multiplier']:.2f}x\nВыигрыш: {win:.2f} USDT",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="💎 Играть снова", callback_data="play_again")]]
        )
    )
    await callback.answer()

@dp.callback_query(F.data == "exit")
async def exit_game(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    if user_id in user_games:
        user_games.pop(user_id)
    
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("❌ Вы вышли из игры.")
    await callback.answer()

@dp.callback_query(F.data == "play_again")
async def play_again(callback: types.CallbackQuery):
    await callback.message.answer("🛩️ Введи новую сумму ставки:")
    await callback.answer()

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
