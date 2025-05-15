import logging
from aiogram import Bot, Dispatcher, executor, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime, timedelta
import sqlite3
import os

API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# Configure logging
logging.basicConfig(level=logging.INFO)

# Initialize bot and dispatcher
bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# SQLite setup
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

# Define states
class TaskCreation(StatesGroup):
    ChoosingUser = State()
    EnteringText = State()
    ChoosingDeadline = State()
    EnteringDate = State()

user_map = {
    "muzalevskyim": "@muzalevskyim",
    "criypto_investor": "@criypto_investor"
}

@dp.message_handler(commands=["start", "help", "ping"])
async def send_welcome(message: types.Message):\n    await message.reply(f"Chat ID: {message.chat.id}")
    await message.reply("Привет! Используй /новая для создания новой задачи. /готово <id> — чтобы завершить.")

@dp.message_handler(commands=["новая"])
async def new_task(message: types.Message):
    keyboard = InlineKeyboardMarkup(row_width=2)
    for key in user_map:
        keyboard.add(InlineKeyboardButton(text=user_map[key], callback_data=f"user_{key}"))
    await message.answer("Кому назначить задачу?", reply_markup=keyboard)
    await TaskCreation.ChoosingUser.set()

@dp.callback_query_handler(lambda c: c.data.startswith("user_"), state=TaskCreation.ChoosingUser)
async def process_user(callback_query: types.CallbackQuery, state: FSMContext):
    user_key = callback_query.data.split("_")[1]
    await state.update_data(user=user_key, creator=callback_query.from_user.username)
    await bot.send_message(callback_query.from_user.id, "Введите текст задачи:")
    await TaskCreation.Next()

@dp.message_handler(state=TaskCreation.EnteringText)
async def process_text(message: types.Message, state: FSMContext):
    await state.update_data(text=message.text)
    keyboard = InlineKeyboardMarkup(row_width=3)
    keyboard.add(
        InlineKeyboardButton("Сегодня", callback_data="deadline_today"),
        InlineKeyboardButton("Завтра", callback_data="deadline_tomorrow"),
        InlineKeyboardButton("Ввести дату", callback_data="deadline_custom")
    )
    await message.answer("Выберите срок выполнения задачи:", reply_markup=keyboard)
    await TaskCreation.Next()

@dp.callback_query_handler(lambda c: c.data.startswith("deadline_"), state=TaskCreation.ChoosingDeadline)
async def process_deadline(callback_query: types.CallbackQuery, state: FSMContext):
    if callback_query.data == "deadline_today":
        deadline = datetime.now().strftime("%Y-%m-%d")
    elif callback_query.data == "deadline_tomorrow":
        deadline = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        await bot.send_message(callback_query.from_user.id, "Введите дату в формате ГГГГ-ММ-ДД:")
        await TaskCreation.Next()
        return
    await finalize_task(callback_query.from_user.id, state, deadline)

@dp.message_handler(state=TaskCreation.EnteringDate)
async def custom_deadline(message: types.Message, state: FSMContext):
    try:
        deadline = datetime.strptime(message.text.strip(), "%Y-%m-%d").strftime("%Y-%m-%d")
        await finalize_task(message.from_user.id, state, deadline)
    except ValueError:
        await message.reply("Неверный формат даты. Попробуйте ещё раз (ГГГГ-ММ-ДД).")

async def finalize_task(user_id, state: FSMContext, deadline):
    data = await state.get_data()
    cursor.execute("INSERT INTO tasks (user, creator, text, deadline) VALUES (?, ?, ?, ?)",
                   (data['user'], data['creator'], data['text'], deadline))
    conn.commit()
    task_id = cursor.lastrowid
    assigned_user = user_map[data['user']]
    msg = f"🆕 Новая задача для {assigned_user}:

📌 {data['text']}
🗓 Дедлайн: {deadline}
🆔 #{task_id}"
    await bot.send_message(CHAT_ID, msg)
    await bot.send_message(assigned_user, msg)
    await state.finish()

@dp.message_handler(lambda message: message.text.startswith("/готово"))
async def complete_task(message: types.Message):
    try:
        task_id = int(message.text.split()[1])
        cursor.execute("SELECT text, user FROM tasks WHERE id=? AND completed=0", (task_id,))
        task = cursor.fetchone()
        if task:
            cursor.execute("UPDATE tasks SET completed=1 WHERE id=?", (task_id,))
            conn.commit()
            await bot.send_message(CHAT_ID, f"✅ Задача #{task_id} завершена @{message.from_user.username}:
📌 {task[0]}")
            await bot.send_message(user_map[task[1]], f"✅ Ваша задача #{task_id} завершена @{message.from_user.username}:
📌 {task[0]}")
        else:
            await message.reply("Задача не найдена или уже завершена.")
    except:
        await message.reply("Формат: /готово <ID задачи>")

# Напоминания
scheduler = AsyncIOScheduler()

def check_deadlines():
    today = datetime.now().date()
    cursor.execute("SELECT id, text, user, deadline FROM tasks WHERE completed=0")
    for row in cursor.fetchall():
        task_id, text, user, deadline = row
        try:
            d_date = datetime.strptime(deadline, "%Y-%m-%d").date()
            if d_date == today:
                msg = f"⚠️ Сегодня дедлайн по задаче #{task_id}:
📌 {text}"
            elif d_date < today:
                msg = f"⏰ Просрочена задача #{task_id} (дедлайн {deadline}):
📌 {text}"
            else:
                continue
            bot.loop.create_task(bot.send_message(CHAT_ID, msg))
            bot.loop.create_task(bot.send_message(user_map[user], msg))
        except Exception as e:
            logging.error(f"Deadline check error: {e}")

scheduler.add_job(check_deadlines, "cron", hour=9)  # каждый день в 9:00
scheduler.start()

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)