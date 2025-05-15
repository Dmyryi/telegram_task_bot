import asyncio
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import API_TOKEN
from handlers import task_create, task as deadline_scheduler

bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
scheduler = AsyncIOScheduler()

def register_all_handlers():
    dp.include_routers(
       
        task_create.router,
        task.router,
    
    )

async def main():
    from handlers.commands import setup_commands
    scheduler.start()
    register_all_handlers()
    await setup_commands(bot)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
