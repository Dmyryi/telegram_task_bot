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

print("DEBUG >>", dict(os.environ))
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
    "muzalevskyim": {
        "chat_id": 514324714,
        "username": "@muzalevskyim"
    },
    "criypto_investor": {
        "chat_id": 767518219,
        "username": "@criypto_investor"
    }
}

@dp.message(Command("start"))
async def send_welcome(message: Message):
    await message.answer(f"<b>Chat ID</b>: <code>{message.chat.id}</code>")
    await message.answer("Привет! Используй /new для создания новой задачи. /ready — чтобы завершить задачу. /mytasks — посмотреть свои задачи. /alltasks — посмотреть все задачи.")

@dp.message(Command("new"))
async def new_task(message: Message, state: FSMContext):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for key in user_map:
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text=user_map[key]["username"], callback_data=f"user_{key}")
        ])
    await message.answer("Кому назначить задачу?", reply_markup=keyboard)
    await state.set_state(TaskCreation.ChoosingUser)

@dp.callback_query(F.data.startswith("user_"), TaskCreation.ChoosingUser)
async def process_user(callback_query: types.CallbackQuery, state: FSMContext):
    user_key = callback_query.data.split("_")[1]
    await state.update_data(user=user_key, creator=callback_query.from_user.username)
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
    await message.answer("Выберите срок выполнения задачи:", reply_markup=keyboard)
    await state.set_state(TaskCreation.ChoosingDeadline)

@dp.callback_query(F.data.startswith("deadline_"), TaskCreation.ChoosingDeadline)
async def process_deadline(callback_query: types.CallbackQuery, state: FSMContext):
    if callback_query.data == "deadline_today":
        deadline = datetime.now().strftime("%Y-%m-%d")
    elif callback_query.data == "deadline_tomorrow":
        deadline = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        await bot.send_message(callback_query.from_user.id, "Введите дату в формате ГГГГ-ММ-ДД:")
        await state.set_state(TaskCreation.EnteringDate)
        return
    await finalize_task(callback_query.from_user.id, state, deadline)

@dp.message(TaskCreation.EnteringDate)
async def custom_deadline(message: Message, state: FSMContext):
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
    msg = f"""🆕 Новая задача для {assigned_user['username']}:
\n📌 {data['text']}\n📅 Дедлайн: {deadline}\n🆔 #{task_id}"""
    await bot.send_message(CHAT_ID, msg)
    try:
        await bot.send_message(assigned_user["chat_id"], msg)
    except Exception as e:
        logging.warning(f"Не удалось отправить личное сообщение: {e}")
    await state.clear()

@dp.message(Command("ready"))
async def choose_task_to_complete(message: Message, state: FSMContext):
    user_key = message.from_user.username
    if not user_key:
        await message.answer("⚠️ У вас нет username. Укажите его в Telegram настройках.")
        return
    cursor.execute("SELECT id, text FROM tasks WHERE user=? AND completed=0", (user_key,))
    tasks = cursor.fetchall()
    if not tasks:
        await message.answer("✅ У вас нет незавершённых задач.")
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"#{tid}: {text[:30]}", callback_data=f"done_{tid}")]
        for tid, text in tasks
    ])
    await message.answer("Выберите задачу, которую хотите завершить:", reply_markup=keyboard)
    await state.set_state(TaskCompletion.ChoosingTask)

@dp.callback_query(F.data.startswith("done_"), TaskCompletion.ChoosingTask)
async def complete_selected_task(callback_query: types.CallbackQuery, state: FSMContext):
    task_id = int(callback_query.data.split("_")[1])
    cursor.execute("SELECT text FROM tasks WHERE id=? AND completed=0", (task_id,))
    task = cursor.fetchone()
    if not task:
        await callback_query.message.edit_text("❌ Задача не найдена или уже завершена.")
        await state.clear()
        return
    task_text = task[0]
    cursor.execute("UPDATE tasks SET completed=1 WHERE id=?", (task_id,))
    conn.commit()
    done_msg = f"✅ Задача #{task_id} завершена @{callback_query.from_user.username}:\n📌 {task_text}"
    await bot.send_message(CHAT_ID, done_msg)
    user_key = callback_query.from_user.username
    if user_key in user_map and isinstance(user_map[user_key], dict):
        try:
            await bot.send_message(user_map[user_key]["chat_id"], done_msg)
        except:
            pass
    await callback_query.message.edit_text(f"✅ Задача #{task_id} завершена.")
    await state.clear()

@dp.message(Command("mytasks"))
async def show_mytasks_buttons(message: Message):
    user_key = message.from_user.username
    if not user_key:
        await message.answer("⚠️ У вас нет username. Укажите его в Telegram настройках.")
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🟡 In progress", callback_data=f"my_active_{user_key}"),
            InlineKeyboardButton(text="✅ Done", callback_data=f"my_done_{user_key}"),
            InlineKeyboardButton(text="💩 Deadline", callback_data=f"my_overdue_{user_key}")
        ]
    ])

    await message.answer("Какие задачи показать?", reply_markup=keyboard)

@dp.callback_query(F.data.startswith("my_active_"))
async def show_my_active(callback: types.CallbackQuery):
    user_key = callback.data.split("_")[2]
    cursor.execute("SELECT id, text, deadline FROM tasks WHERE completed = 0 AND user = ? ORDER BY deadline", (user_key,))
    tasks = cursor.fetchall()
    if not tasks:
        await callback.message.edit_text("🟡 У вас нет активных задач.")
        return
    lines = [f"#{tid} — {text[:40]}\n📅 Dea: {deadline} | 🕒 В работе" for tid, text, deadline in tasks]
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🟡 In progress", callback_data=f"my_active_{user_key}"),
            InlineKeyboardButton(text="✅ Done", callback_data=f"my_done_{user_key}"),
            InlineKeyboardButton(text="💩 Deadline", callback_data=f"my_overdue_{user_key}")
        ]
    ])

    await callback.message.edit_text("<b>🟡 Мои активные задачи:</b>\n\n" + "\n\n".join(lines), reply_markup=keyboard, parse_mode="HTML")


@dp.callback_query(F.data.startswith("my_overdue_"))
async def show_my_overdue(callback: types.CallbackQuery):
    user_key = callback.data.split("_")[2]
    today = datetime.now().date()

    cursor.execute(
        "SELECT id, text, deadline FROM tasks WHERE completed = 0 AND user = ? AND deadline < ? ORDER BY deadline",
        (user_key, today.strftime("%Y-%m-%d"))
    )
    tasks = cursor.fetchall()

    if not tasks:
        await callback.message.edit_text("💩 У вас нет просроченных задач.")
        return

    lines = [f"#{tid} — {text[:40]}\n📅Deadline: {deadline}|💩Просрочена" for tid, text, deadline in tasks]

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🟡 In progress", callback_data=f"my_active_{user_key}"),
            InlineKeyboardButton(text="✅ Done", callback_data=f"my_done_{user_key}"),
            InlineKeyboardButton(text="💩 Deadline", callback_data=f"my_overdue_{user_key}")
        ]
    ])


    await callback.message.edit_text(
        "<b>💩 Мои просроченные задачи:</b>\n\n" + "\n\n".join(lines),
        reply_markup=keyboard,
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("my_done_"))
async def show_my_done(callback: types.CallbackQuery):
    user_key = callback.data.split("_")[2]
    cursor.execute("SELECT id, text, deadline FROM tasks WHERE completed = 1 AND user = ? ORDER BY deadline DESC", (user_key,))
    tasks = cursor.fetchall()
    if not tasks:
        await callback.message.edit_text("✅ У вас нет завершённых задач.")
        return
    lines = [f"#{tid} — {text[:40]}\n📅Deadline:{deadline}|✅Завершена" for tid, text, deadline in tasks]
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🟡 In progress", callback_data=f"my_active_{user_key}"),
            InlineKeyboardButton(text="✅ Done", callback_data=f"my_done_{user_key}"),
            InlineKeyboardButton(text="💩 Deadline", callback_data=f"my_overdue_{user_key}")
        ]
    ])

    await callback.message.edit_text("<b>✅ Мои завершённые задачи:</b>\n\n" + "\n\n".join(lines), reply_markup=keyboard, parse_mode="HTML")


@dp.message(Command("alltasks"))
async def show_alltasks_buttons(message: Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🟡 In progress", callback_data="show_active"),
            InlineKeyboardButton(text="✅ Done", callback_data="show_done"),
            InlineKeyboardButton(text="💩 Deadline", callback_data="show_overdue")
        ]
    ])

    await message.answer("Выберите, какие задачи показать:", reply_markup=keyboard)

@dp.callback_query(F.data == "show_active")
async def show_active_tasks(callback: types.CallbackQuery):
    cursor.execute("SELECT id, text, deadline, user FROM tasks WHERE completed = 0 ORDER BY deadline")
    tasks = cursor.fetchall()

    if not tasks:
        await callback.message.edit_text("🟡 Активных задач нет.")
        return

    lines = []
    for tid, text, deadline, user in tasks:
        user_display = user_map.get(user, {}).get("username", user)
        lines.append(f"#{tid} для {user_display} — {text[:40]}\n📅Deadline:{deadline}|🕒В работе")

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🟡 In progress", callback_data="show_active"),
            InlineKeyboardButton(text="✅ Done", callback_data="show_done"),
            InlineKeyboardButton(text="💩 Deadline", callback_data="show_overdue")
        ]
    ])
    await callback.message.edit_text("<b>🟡 Активные задачи:</b>\n\n" + "\n\n".join(lines), reply_markup=keyboard, parse_mode="HTML")


@dp.callback_query(F.data == "show_overdue")
async def show_overdue_tasks(callback: types.CallbackQuery):
    today = datetime.now().date()

    cursor.execute(
        "SELECT id, text, deadline, user FROM tasks WHERE completed = 0 AND deadline < ? ORDER BY deadline",
        (today.strftime("%Y-%m-%d"),)
    )
    tasks = cursor.fetchall()

    if not tasks:
        await callback.message.edit_text("💩 Просроченных задач нет.")
        return

    lines = []
    for tid, text, deadline, user in tasks:
        user_display = user_map.get(user, {}).get("username", user)
        lines.append(f"#{tid} для {user_display} — {text[:40]}\n📅Deadline:{deadline}|💩Просрочена")

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🟡 In progress", callback_data="show_active"),
            InlineKeyboardButton(text="✅ Done", callback_data="show_done"),
            InlineKeyboardButton(text="💩 Deadline", callback_data="show_overdue")
        ]
    ])

    await callback.message.edit_text(
        "<b>💩 Просроченные задачи:</b>\n\n" + "\n\n".join(lines),
        reply_markup=keyboard,
        parse_mode="HTML"
    )


@dp.callback_query(F.data == "show_done")
async def show_done_tasks(callback: types.CallbackQuery):
    cursor.execute("SELECT id, text, deadline, user FROM tasks WHERE completed = 1 ORDER BY deadline DESC")
    tasks = cursor.fetchall()

    if not tasks:
        await callback.message.edit_text("✅ Завершённых задач нет.")
        return

    lines = []
    for tid, text, deadline, user in tasks:
        user_display = user_map.get(user, {}).get("username", user)
        lines.append(f"#{tid} для {user_display} — {text[:40]}\n📅Deadline:{deadline}|✅Завершена")

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🟡 In progress", callback_data="show_active"),
            InlineKeyboardButton(text="✅ Done", callback_data="show_done"),
            InlineKeyboardButton(text="💩 Deadline", callback_data="show_overdue")
        ]
    ])
    await callback.message.edit_text("<b>✅ Завершённые задачи:</b>\n\n" + "\n\n".join(lines), reply_markup=keyboard, parse_mode="HTML")



scheduler = AsyncIOScheduler()
scheduler.add_job(lambda: asyncio.create_task(run_check_deadlines()), "cron", hour=9)


@dp.message(Command("check"))
async def manual_check(message: Message):
    await run_check_deadlines()
    await message.answer("✅ Проверка дедлайнов выполнена вручную.")


async def run_check_deadlines():
    today = datetime.now().date()
    cursor.execute("SELECT id, text, user, deadline FROM tasks WHERE completed=0")
    for row in cursor.fetchall():
        task_id, text, user, deadline = row
        try:
            d_date = datetime.strptime(deadline, "%Y-%m-%d").date()
            if d_date == today:
                msg = f"⚠️ Сегодня дедлайн по задаче #{task_id}:\n📌 {text}"
            elif d_date < today:
                msg = f"💩 Просрочена задача #{task_id} (дедлайн {deadline}):\n📌 {text}"
            else:
                continue
            await bot.send_message(CHAT_ID, msg)
            await bot.send_message(user_map[user]["chat_id"], msg)
        except Exception as e:
            logging.error(f"Deadline check error: {e}")

async def main():
    scheduler.start()

    commands = [
        BotCommand(command="start", description="Начать работу с ботом"),
        BotCommand(command="new", description="Создать новую задачу"),
        BotCommand(command="ready", description="Завершить задачу"),
        BotCommand(command="mytasks", description="Мои задачи (активные/завершённые)"),
        BotCommand(command="alltasks", description="Все задачи в системе  (активные/завершённые)"),
        BotCommand(command="check", description="Ручная проверка дедлайнов")
    ]

    await bot.set_my_commands(commands)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
