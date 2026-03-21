from aiogram import Bot, Dispatcher, types, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
import asyncio
import os

TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(token=TOKEN)
dp = Dispatcher()

def get_check_button():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔍 Проверить", callback_data="check_profile")]
        ]
    )

@dp.message(Command("start"))
async def start(message: Message):
    await message.answer(
        "Нажми на кнопку, чтобы проверить профиль",
        reply_markup=get_check_button()
    )

@dp.callback_query(F.data == "check_profile")
async def check_profile(callback: types.CallbackQuery):
    first_name = callback.from_user.first_name or ""
    bio = callback.from_user.bio or ""
    
    if "@JOPA" in first_name and "A" in bio:
        await callback.answer("🎉 Вы участвуете!", show_alert=True)
    else:
        await callback.answer("❌ Условия не выполнены", show_alert=True)

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
