# main.py
import asyncio
from bot import bot, TOKEN, start_web_server

async def main():
    async with bot:
        await start_web_server()
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
