from aiogram import Bot, Dispatcher, types, F
from aiogram.types import Message
import asyncio
import os
import logging

logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("TOKEN")
bot = Bot(token=TOKEN)
dp = Dispatcher()

user_data = {}

@dp.message()
async def start(message: Message):
    await message.answer("Введи любое число (например 5)")
    user_data[message.from_user.id] = {}

@dp.message()
async def handle_number(message: Message):
    try:
        bet = float(message.text)
        user_data[message.from_user.id] = {"bet": bet}
        logging.info(f"User {message.from_user.id} bet {bet}, sending dice...")
        await message.reply_dice(emoji="🎲")
    except:
        await message.answer("Введи число")

@dp.message(F.dice)
async def dice_result(message: Message):
    dice_value = message.dice.value
    user_id = message.from_user.id
    
    logging.info(f"Dice received from {user_id}, value: {dice_value}")
    
    if user_id in user_data:
        bet = user_data[user_id]["bet"]
        result = "✅ Победа!" if dice_value % 2 == 0 else "🚫 Поражение!"
        await message.answer(f"{result}\nВыпало: {dice_value}\nСтавка: {bet}")
        del user_data[user_id]
    else:
        await message.answer(f"Выпало: {dice_value}")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
