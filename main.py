from aiogram import Bot, Dispatcher, types, F
from aiogram.types import Message
from aiogram.filters import Command
import asyncio
import os
import logging

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("Токен не найден!")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def start(message: Message):
    await message.answer("Кидаю кубик...")
    dice_msg = await bot.send_dice(chat_id=message.chat.id, emoji="🎲")
    value = dice_msg.dice.value
    await asyncio.sleep(2)
    await message.answer(f"🎲 Выпало: {value}")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
