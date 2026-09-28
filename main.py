import os
import asyncio
from bot import bot, TOKEN, start_web_server

async def runner():
    if not TOKEN:
        print("❌ خطأ: لم يتم العثور على التوكن (dsct / DISCORD_TOKEN) في متغيرات البيئة!")
        return

    async with bot:
        # تشغيل سيرفر الويب لضمان بقاء البوت حياً (Keep-Alive)
        await start_web_server()
        # تشغيل بوت ديسكورد
        await bot.start(TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(runner())
    except KeyboardInterrupt:
        print("\n🛑 تم إيقاف البوت يدوياً.")
