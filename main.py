import logging
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, BotCommand
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.client.default import DefaultBotProperties
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime, timedelta
from aiogram.filters import Command
import sqlite3
import os
from dotenv import load_dotenv

load_dotenv()

API_TOKEN = os.environ["API_TOKEN"]
CHAT_ID = int(os.environ["CHAT_ID"])

logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

conn = sqlite3.connect("tasks.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user TEXT,
    creator TEXT,
    text TEXT,
    deadline TEXT,
    completed INTEGER DEFAULT 0
)
''')
conn.commit()

class TaskCreation(StatesGroup):
    ChoosingUser = State()
    EnteringText = State()
    ChoosingDeadline = State()
    EnteringDate = State()

class TaskCompletion(StatesGroup):
    ChoosingTask = State()

user_map = {
    "muzalevskyim": {"chat_id": 514324714, "username": "@muzalevskyim"},
    "criypto_investor": {"chat_id": 767518219, "username": "@criypto_investor"},
    "Dmytryi_Muzalevskyi": {"chat_id": 893738240, "username": "@Dmytryi_Muzalevskyi"}
}

@dp.message(Command("start"))
async def send_welcome(message: Message):
    await message.answer(f"<b>Chat ID</b>: <code>{message.chat.id}</code>")
    await message.answer("Привет! Используй /new для создания задачи. /ready — завершить. /mytasks — мои задачи.")

@dp.message(Command("new"))
async def new_task(message: Message, state: FSMContext):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=info["username"], callback_data=f"user_{key}")]
        for key, info in user_map.items()
    ])
    await message.answer("Кому назначить задачу?", reply_markup=keyboard)
    await state.set_state(TaskCreation.ChoosingUser)

@dp.callback_query(F.data.startswith("user_"), TaskCreation.ChoosingUser)
async def process_user(callback_query: types.CallbackQuery, state: FSMContext):
    user_key = callback_query.data.split("user_")[1]
    await state.update_data(user=user_key, creator=callback_query.from_user.username.lstrip("@"))
    await callback_query.message.answer("Введите текст задачи:")
    await state.set_state(TaskCreation.EnteringText)

@dp.message(TaskCreation.EnteringText)
async def process_text(message: Message, state: FSMContext):
    await state.update_data(text=message.text)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Сегодня", callback_data="deadline_today")],
        [InlineKeyboardButton(text="Завтра", callback_data="deadline_tomorrow")],
        [InlineKeyboardButton(text="Ввести дату", callback_data="deadline_custom")]
    ])
    await message.answer("Выберите срок выполнения:", reply_markup=keyboard)
    await state.set_state(TaskCreation.ChoosingDeadline)

@dp.callback_query(F.data.startswith("deadline_"), TaskCreation.ChoosingDeadline)
async def process_deadline(callback_query: types.CallbackQuery, state: FSMContext):
    if callback_query.data == "deadline_today":
        deadline = datetime.now().strftime("%Y-%m-%d")
    elif callback_query.data == "deadline_tomorrow":
        deadline = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        await bot.send_message(callback_query.from_user.id, "Введите дату (ГГГГ-ММ-ДД):")
        await state.set_state(TaskCreation.EnteringDate)
        return
    await finalize_task(callback_query.from_user.username, state, deadline)

@dp.message(TaskCreation.EnteringDate)
async def custom_deadline(message: Message, state: FSMContext):
    try:
        deadline = datetime.strptime(message.text.strip(), "%Y-%m-%d").strftime("%Y-%m-%d")
        await finalize_task(message.from_user.username, state, deadline)
    except ValueError:
        await message.reply("Неверный формат даты. Попробуйте ещё раз (ГГГГ-ММ-ДД).")

async def finalize_task(username, state: FSMContext, deadline):
    data = await state.get_data()
    user = data['user']
    creator = data['creator']
    text = data['text']
    cursor.execute("INSERT INTO tasks (user, creator, text, deadline) VALUES (?, ?, ?, ?)",
                   (user, creator, text, deadline))
    conn.commit()
    task_id = cursor.lastrowid

    assigned_user = user_map.get(user)
    if not assigned_user:
        await bot.send_message(CHAT_ID, f"❌ Ошибка: пользователь {user} не найден")
        return

    msg = f"🆕 Новая задача для {assigned_user['username']}\n📌 {text}\n📅 Дедлайн: {deadline}\n🆔 #{task_id}"
    await bot.send_message(CHAT_ID, msg)
    await bot.send_message(assigned_user["chat_id"], msg)
    await state.clear()

async def main():
    scheduler = AsyncIOScheduler()
    scheduler.start()

    await bot.set_my_commands([
        BotCommand(command="start", description="Начать"),
        BotCommand(command="new", description="Новая задача"),
        BotCommand(command="ready", description="Завершить задачу"),
        BotCommand(command="mytasks", description="Мои задачи")
    ])
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
