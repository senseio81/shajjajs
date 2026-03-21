from aiogram import Bot, Dispatcher, types, F
from aiogram.types import Message
from aiogram.filters import Command
import asyncio
import os
import logging

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(Command("dice"))
async def dice_cmd(message: Message):
    await message.answer_dice(emoji="🎲")

@dp.message(F.dice)
async def dice_result(message: Message):
    logging.info(f"Dice received: {message.dice.value}")
    await message.reply(f"🎲 Выпало: {message.dice.value}")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
