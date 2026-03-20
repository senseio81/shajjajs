import asyncio
import os
from aiogram import Bot, Dispatcher, Router
from aiogram.types import Message
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
EMOJI_ID = "5413879192267805083"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

@router.message()
async def handle(message: Message):
    await message.answer(
        f'<tg-emoji emoji-id="{EMOJI_ID}">🎲</tg-emoji>',
        parse_mode="HTML"
    )

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
