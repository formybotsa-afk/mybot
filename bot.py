import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Button
import random
import time
import json
import os
import io
import asyncio
from datetime import timedelta, date
import jinja2
import aiohttp_jinja2
from aiohttp import web

# =========================
# ⚙️ الإعدادات والمتغيرات
# =========================
TOKEN = os.getenv("dsct")
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "admin123")
SESSION_SECRET = os.urandom(16).hex()

DATA_FILE = "economy.json"
WARN_FILE = "warnings.json"
TICKET_CONFIG_FILE = "ticket_config.json"
TICKET_DATA_FILE = "tickets.json"

DAILY_AMOUNT = 100
ALLOWED_ROLE_NAME = "__  SA | ALONE   __"

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

spam = {}
mrbeast_room = None


# =========================
# 💾 حفظ وتحميل البيانات
# =========================
def load_json(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

money = load_json(DATA_FILE)
warnings_db = load_json(WARN_FILE)
ticket_config = load_json(TICKET_CONFIG_FILE)
if not ticket_config:
    ticket_config = {"category_id": None, "support_role_id": None, "log_channel_id": None, "counter": 0}
tickets_db = load_json(TICKET_DATA_FILE)


def is_ticket_staff(member: discord.Member) -> bool:
    role_id = ticket_config.get("support_role_id")
    if role_id and discord.utils.get(member.roles, id=role_id):
        return True
    if discord.utils.get(member.roles, name=ALLOWED_ROLE_NAME):
        return True
    return False

def get_user(uid: int):
    uid = str(uid)
    if uid not in money:
        money[uid] = {"balance": 0, "last_daily_date": None}
    return money[uid]


# =========================
# 🔐 فحص الرول المسموح
# =========================
class NotAllowedRole(app_commands.CheckFailure):
    pass

def is_allowed_role():
    async def predicate(interaction: discord.Interaction) -> bool:
        if isinstance(interaction.user, discord.Member):
            role = discord.utils.get(interaction.user.roles, name=ALLOWED_ROLE_NAME)
            if role is not None:
                return True
        raise NotAllowedRole()
    return app_commands.check(predicate)


# =========================
# 🌐 لوحة التحكم وسيرفر الويب (Dashboard & Web Server)
# =========================
def check_auth(request):
    cookies = request.cookies
    return cookies.get("auth_session") == SESSION_SECRET

async def http_login_page(request):
    if check_auth(request):
        return web.HTTPFound('/dashboard')
    return aiohttp_jinja2.render_template('login.html', request, {})

async def http_login_submit(request):
    data = await request.post()
    password = data.get("password")
    if password == DASHBOARD_PASSWORD:
        response = web.HTTPFound('/dashboard')
        response.set_cookie('auth_session', SESSION_SECRET, max_age=3600*24)
        return response
    return aiohttp_jinja2.render_template('login.html', request, {'error': 'كلمة السر غير صحيحة!'})

async def http_logout(request):
    response = web.HTTPFound('/login')
    response.del_cookie('auth_session')
    return response

async def http_dashboard(request):
    if not check_auth(request):
        return web.HTTPFound('/login')

    stats = {
        "guilds": len(bot.guilds),
        "users": sum(g.member_count for g in bot.guilds),
        "ping": round(bot.latency * 1000) if bot.latency else 0
    }

    channels = []
    for guild in bot.guilds:
        for ch in guild.text_channels:
            channels.append({"id": str(ch.id), "name": ch.name, "guild": guild.name})

    return aiohttp_jinja2.render_template('dashboard.html', request, {
        'stats': stats,
        'channels': channels
    })

async def api_send_message(request):
    if not check_auth(request):
        return web.HTTPUnauthorized()
    data = await request.post()
    channel_id = int(data.get("channel_id"))
    msg = data.get("message")
    
    channel = bot.get_channel(channel_id)
    if channel:
        await channel.send(msg)
        return web.Response(text="<script>alert('تم إرسال الرسالة بنجاح!'); window.location.href='/dashboard';</script>", content_type="text/html")
    return web.Response(text="<script>alert('تعذر العثور على الروم'); window.location.href='/dashboard';</script>", content_type="text/html")

async def api_modify_balance(request):
    if not check_auth(request):
        return web.HTTPUnauthorized()
    data = await request.post()
    uid = str(data.get("user_id")).strip()
    amount = int(data.get("amount", 0))
    action = data.get("action")

    user_data = get_user(uid)
    if action == "add":
        user_data["balance"] += amount
    else:
        user_data["balance"] = max(0, user_data["balance"] - amount)
    
    save_json(DATA_FILE, money)
    return web.Response(text="<script>alert('تم تحديث رصيد العضو بنجاح!'); window.location.href='/dashboard';</script>", content_type="text/html")

async def start_web_server():
    app = web.Application()
    aiohttp_jinja2.setup(app, loader=jinja2.FileSystemLoader(os.path.join(os.path.dirname(__file__), 'templates')))

    app.router.add_get('/', lambda r: web.HTTPFound('/dashboard'))
    app.router.add_get('/login', http_login_page)
    app.router.add_post('/login', http_login_submit)
    app.router.add_get('/logout', http_logout)
    app.router.add_get('/dashboard', http_dashboard)
    
    app.router.add_post('/api/send_message', api_send_message)
    app.router.add_post('/api/modify_balance', api_modify_balance)

    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"🌐 Dashboard Web Server running on port {port}")


# =========================
# 🧠 الأحداث ومكافحة السبام
# =========================
@bot.event
async def on_message(message: discord.Message):
    global mrbeast_room

    if message.author.bot:
        return

    if mrbeast_room and message.channel.id == mrbeast_room:
        try:
            await message.delete()
        except Exception:
            pass
        try:
            await message.author.ban(reason="إرسال ممنوع في روم الباند")
        except Exception:
            pass
        return

    uid = message.author.id
    now = time.time()

    spam.setdefault(uid, []).append(now)
    spam[uid] = [t for t in spam[uid] if now - t < 5]

    if len(spam[uid]) >= 6:
        try:
            await message.author.timeout(timedelta(minutes=2), reason="سبام")
        except Exception:
            pass
        spam[uid] = []

    await bot.process_commands(message)


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    original = getattr(error, "original", None)
    if isinstance(error, discord.NotFound) or isinstance(original, discord.NotFound):
        print("⚠️ Interaction انتهت قبل الرد، تم التجاهل بأمان.")
        return

    if isinstance(error, NotAllowedRole):
        msg = f"🚫 هذا الأمر مخصص فقط لأصحاب رول **{ALLOWED_ROLE_NAME}**."
    elif isinstance(error, app_commands.MissingPermissions):
        msg = "🚫 ما عندك الصلاحية الكافية لاستخدام هذا الأمر."
    elif isinstance(error, app_commands.CommandOnCooldown):
        msg = f"⏳ لازم تنتظر {round(error.retry_after)} ثانية قبل استخدام الأمر مرة ثانية."
    elif isinstance(error, app_commands.BotMissingPermissions):
        msg = "🚫 البوت ما عنده الصلاحية الكافية لتنفيذ هذا الأمر."
    else:
        msg = f"❌ صار خطأ: `{error}`"

    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception as e:
        print(f"⚠️ فشل إرسال الخطأ: {e}")


# =========================
# 📋 SAY & SAY_EMBED
# =========================
class SayView(View):
    def __init__(self, text):
        super().__init__(timeout=None)
        btn = Button(label="📋 نسخ")

        async def copy(i):
            await i.response.send_message(f"```{text}```", ephemeral=True)

        btn.callback = copy
        self.add_item(btn)

@bot.tree.command(name="say", description="يخلي البوت يرسل رسالة")
@is_allowed_role()
async def say(interaction: discord.Interaction, text: str, hidden: bool = False):
    await interaction.response.send_message(text, view=SayView(text), ephemeral=hidden)

@bot.tree.command(name="say_embed", description="يرسل embed مخصص")
@is_allowed_role()
async def say_embed(interaction: discord.Interaction, title: str, desc: str):
    embed = discord.Embed(title=title, description=desc, color=0x00FF99)
    embed.set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar)
    await interaction.response.send_message(embed=embed)


# =========================
# 📜 نظام السكربتات
# =========================
class CopyButtons(View):
    def __init__(self, script_text):
        super().__init__(timeout=None)
        m = Button(label="📱 نسخ للجوال", style=discord.ButtonStyle.green)
        pc = Button(label="💻 نسخ للبي سي", style=discord.ButtonStyle.blurple)

        async def cm_cb(i):
            await i.response.send_message(f"`{script_text}`", ephemeral=True)

        async def cp_cb(i):
            await i.response.send_message(f"```{script_text}```", ephemeral=True)

        m.callback = cm_cb
        pc.callback = cp_cb

        self.add_item(m)
        self.add_item(pc)

class ScriptModal(discord.ui.Modal, title="إنشاء سكربت"):
    map_name = discord.ui.TextInput(label="🎮 اسم الماب")
    script_input = discord.ui.TextInput(label="📜 السكربت", style=discord.TextStyle.paragraph)

    async def on_submit(self, interaction: discord.Interaction):
        server = interaction.guild.name if interaction.guild else "Server"
        embed = discord.Embed(title=f"🎮 سكربت ماب: {self.map_name.value}", color=0x00FF99)
        embed.description = (
            f"📱 **نسخ للجوال**\n`{self.script_input.value}`\n\n"
            f"💻 **نسخ للبي سي**\n```{self.script_input.value}```"
        )
        embed.set_footer(text=f"© {server}")
        await interaction.response.send_message(embed=embed, view=CopyButtons(self.script_input.value))

class OpenModal(View):
    def __init__(self):
        super().__init__(timeout=None)
        btn = Button(label="➕ إنشاء سكربت")

        async def open_modal(i):
            await i.response.send_modal(ScriptModal())

        btn.callback = open_modal
        self.add_item(btn)

@bot.tree.command(name="script", description="نظام إنشاء ومشاركة السكربتات")
@is_allowed_role()
async def script_cmd(interaction: discord.Interaction):
    embed = discord.Embed(title="📜 نظام السكربتات", description="اضغط الزر واكتب 👇", color=0x0099FF)
    await interaction.response.send_message(embed=embed, view=OpenModal())


# =========================
# 🧹 تنظيف الرسائل والرومات
# =========================
@bot.tree.command(name="clear", description="يحذف عدد معين من الرسائل")
@is_allowed_role()
@app_commands.describe(amount="عدد الرسائل (1-1000)")
async def clear(interaction: discord.Interaction, amount: app_commands.Range[int, 1, 1000]):
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"🧹 تم حذف {len(deleted)} رسالة.", ephemeral=True)

@bot.tree.command(name="clear_images", description="يحذف الرسائل التي فيها مرفقات فقط")
@is_allowed_role()
async def clear_images(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=100, check=lambda m: m.attachments)
    await interaction.followup.send(f"🧹 تم حذف {len(deleted)} رسالة فيها مرفقات.", ephemeral=True)

@bot.tree.command(name="clear_user", description="يحذف آخر رسائل عضو معين")
@is_allowed_role()
@app_commands.describe(member="العضو", amount="عدد الرسائل للتفحص")
async def clear_user(interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[int, 1, 1000] = 100):
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount, check=lambda m: m.author.id == member.id)
    await interaction.followup.send(f"🧹 تم حذف {len(deleted)} رسالة من {member.mention}.", ephemeral=True)

@bot.tree.command(name="clr", description="تنظيف كامل للروم (يعيد إنشاءه بنفس الإعدادات والصلاحيات)")
@is_allowed_role()
async def clr(interaction: discord.Interaction):
    channel = interaction.channel
    position = channel.position
    await interaction.response.send_message("🧹 جاري تنظيف الروم بالكامل...", ephemeral=True)
    new_channel = await channel.clone(reason=f"تنظيف الروم بواسطة {interaction.user}")
    await new_channel.edit(position=position)
    await channel.delete(reason=f"تنظيف الروم بواسطة {interaction.user}")
    await new_channel.send(f"✅ تم تنظيف الروم بواسطة {interaction.user.mention}")


# =========================
# 🚫 روم الباند
# =========================
@bot.tree.command(name="noformrbeast", description="يحوّل هذا الروم لروم باند فوري")
@is_allowed_role()
async def noformrbeast(interaction: discord.Interaction):
    global mrbeast_room
    mrbeast_room = interaction.channel.id
    await interaction.response.send_message("🚫 ممنوع الإرسال هنا - أي رسالة = باند فوري ⚠️")

@bot.tree.command(name="remove_banroom", description="يلغي وضع روم الباند")
@is_allowed_role()
async def remove_banroom(interaction: discord.Interaction):
    global mrbeast_room
    mrbeast_room = None
    await interaction.response.send_message("✅ تم إلغاء روم الباند.")


# =========================
# 🔨 أوامر الإدارة
# =========================
@bot.tree.command(name="kick", description="طرد عضو")
@is_allowed_role()
@app_commands.describe(member="العضو", reason="السبب")
async def kick(interaction: discord.Interaction, member: discord.Member, reason: str = "بدون سبب"):
    await member.kick(reason=reason)
    await interaction.response.send_message(f"👢 تم طرد {member.mention}\nالسبب: {reason}")

@bot.tree.command(name="ban", description="حظر عضو")
@is_allowed_role()
@app_commands.describe(member="العضو", reason="السبب")
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str = "بدون سبب"):
    await member.ban(reason=reason)
    await interaction.response.send_message(f"🔨 تم حظر {member.mention}\nالسبب: {reason}")

@bot.tree.command(name="unban", description="إلغاء حظر عضو عن طريق الآيدي")
@is_allowed_role()
@app_commands.describe(user_id="آيدي العضو")
async def unban(interaction: discord.Interaction, user_id: str):
    try:
        user = await bot.fetch_user(int(user_id))
        await interaction.guild.unban(user)
        await interaction.response.send_message(f"✅ تم إلغاء حظر {user}")
    except Exception:
        await interaction.response.send_message("❌ ما قدرت ألغي الحظر، تأكد من الآيدي.", ephemeral=True)

@bot.tree.command(name="mute", description="إسكات عضو لمدة معينة (بالدقائق)")
@is_allowed_role()
@app_commands.describe(member="العضو", minutes="عدد الدقائق", reason="السبب")
async def mute(interaction: discord.Interaction, member: discord.Member, minutes: app_commands.Range[int, 1, 40320], reason: str = "بدون سبب"):
    await member.timeout(timedelta(minutes=minutes), reason=reason)
    await interaction.response.send_message(f"🔇 تم إسكات {member.mention} لمدة {minutes} دقيقة\nالسبب: {reason}")

@bot.tree.command(name="unmute", description="إلغاء الإسكات عن عضو")
@is_allowed_role()
@app_commands.describe(member="العضو")
async def unmute(interaction: discord.Interaction, member: discord.Member):
    await member.timeout(None)
    await interaction.response.send_message(f"🔊 تم إلغاء الإسكات عن {member.mention}")

@bot.tree.command(name="warn", description="إعطاء تحذير لعضو")
@is_allowed_role()
@app_commands.describe(member="العضو", reason="السبب")
async def warn(interaction: discord.Interaction, member: discord.Member, reason: str = "بدون سبب"):
    uid = str(member.id)
    warnings_db.setdefault(uid, [])
    warnings_db[uid].append(reason)
    save_json(WARN_FILE, warnings_db)
    await interaction.response.send_message(
        f"⚠️ تم تحذير {member.mention}\nالسبب: {reason}\nعدد التحذيرات: {len(warnings_db[uid])}"
    )

@bot.tree.command(name="warnings", description="عرض تحذيرات عضو")
@app_commands.describe(member="العضو")
async def warnings_cmd(interaction: discord.Interaction, member: discord.Member):
    uid = str(member.id)
    user_warnings = warnings_db.get(uid, [])
    if not user_warnings:
        await interaction.response.send_message(f"✅ {member.mention} ما عنده أي تحذير.")
        return
    text = "\n".join(f"{i+1}. {r}" for i, r in enumerate(user_warnings))
    embed = discord.Embed(title=f"⚠️ تحذيرات {member.display_name}", description=text, color=0xFFAA00)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="clear_warnings", description="مسح كل تحذيرات عضو")
@is_allowed_role()
@app_commands.describe(member="العضو")
async def clear_warnings(interaction: discord.Interaction, member: discord.Member):
    warnings_db.pop(str(member.id), None)
    save_json(WARN_FILE, warnings_db)
    await interaction.response.send_message(f"✅ تم مسح تحذيرات {member.mention}")

@bot.tree.command(name="add_role", description="إضافة رول لعضو معين")
@is_allowed_role()
@app_commands.describe(member="العضو", role="الرول المراد إضافته")
async def add_role(interaction: discord.Interaction, member: discord.Member, role: discord.Role):
    try:
        await member.add_roles(role)
        await interaction.response.send_message(f"✅ تم إعطاء الرول {role.mention} لـ {member.mention}")
    except Exception as e:
        await interaction.response.send_message(f"❌ تعذر إضافة الرول: `{e}`", ephemeral=True)

@bot.tree.command(name="remove_role", description="إزالة رول من عضو معين")
@is_allowed_role()
@app_commands.describe(member="العضو", role="الرول المراد إزالته")
async def remove_role(interaction: discord.Interaction, member: discord.Member, role: discord.Role):
    try:
        await member.remove_roles(role)
        await interaction.response.send_message(f"✅ تم إزالة الرول {role.mention} من {member.mention}")
    except Exception as e:
        await interaction.response.send_message(f"❌ تعذر إزالة الرول: `{e}`", ephemeral=True)

@bot.tree.command(name="lock", description="قفل الروم الحالي")
@is_allowed_role()
async def lock_channel(interaction: discord.Interaction):
    await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=False)
    await interaction.response.send_message("🔒 تم قفل الروم بنجاح.")

@bot.tree.command(name="unlock", description="فتح الروم الحالي")
@is_allowed_role()
async def unlock_channel(interaction: discord.Interaction):
    await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=True)
    await interaction.response.send_message("🔓 تم فتح الروم بنجاح.")

@bot.tree.command(name="add_money", description="إضافة رصيد مال لعضو معين")
@is_allowed_role()
@app_commands.describe(member="العضو", amount="المبلغ")
async def add_money(interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[int, 1, None]):
    user = get_user(member.id)
    user["balance"] += amount
    save_json(DATA_FILE, money)
    await interaction.response.send_message(f"💵 تم إضافة `{amount}` عملة لـ {member.mention}. رصيده الجديد: `{user['balance']}`")

@bot.tree.command(name="remove_money", description="خصم رصيد مال من عضو معين")
@is_allowed_role()
@app_commands.describe(member="العضو", amount="المبلغ")
async def remove_money(interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[int, 1, None]):
    user = get_user(member.id)
    user["balance"] = max(0, user["balance"] - amount)
    save_json(DATA_FILE, money)
    await interaction.response.send_message(f"💸 تم خصم `{amount}` عملة من {member.mention}. رصيده الجديد: `{user['balance']}`")


# =========================
# ℹ️ أوامر المعلومات
# =========================
@bot.tree.command(name="userinfo", description="معلومات عن عضو")
@app_commands.describe(member="العضو (اختياري)")
async def userinfo(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    embed = discord.Embed(title=f"ℹ️ معلومات {member.display_name}", color=0x00AAFF)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="🆔 آيدي", value=member.id, inline=True)
    embed.add_field(name="📅 انضم بتاريخ", value=discord.utils.format_dt(member.joined_at, "D"), inline=True)
    embed.add_field(name="🎂 أنشأ حسابه", value=discord.utils.format_dt(member.created_at, "D"), inline=True)
    roles = ", ".join(r.mention for r in member.roles[1:]) or "لا يوجد"
    embed.add_field(name="🎭 الرتب", value=roles, inline=False)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="serverinfo", description="معلومات عن السيرفر")
async def serverinfo(interaction: discord.Interaction):
    guild = interaction.guild
    embed = discord.Embed(title=f"ℹ️ معلومات {guild.name}", color=0x00AAFF)
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    embed.add_field(name="👑 المالك", value=guild.owner.mention if guild.owner else "غير معروف", inline=True)
    embed.add_field(name="👥 الأعضاء", value=guild.member_count, inline=True)
    embed.add_field(name="📅 تاريخ الإنشاء", value=discord.utils.format_dt(guild.created_at, "D"), inline=True)
    embed.add_field(name="💬 عدد الرومات", value=len(guild.channels), inline=True)
    embed.add_field(name="🎭 عدد الرتب", value=len(guild.roles), inline=True)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="avatar", description="عرض صورة عضو بالحجم الكامل")
@app_commands.describe(member="العضو (اختياري)")
async def avatar(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    embed = discord.Embed(title=f"🖼️ صورة {member.display_name}", color=0x00AAFF)
    embed.set_image(url=member.display_avatar.url)
    await interaction.response.send_message(embed=embed)


# =========================
# 💰 نظام الاقتصاد
# =========================
@bot.tree.command(name="daily", description="جمع الراتب اليومي")
async def daily(interaction: discord.Interaction):
    user = get_user(interaction.user.id)
    today = date.today().isoformat()

    if user.get("last_daily_date") == today:
        embed = discord.Embed(title="⏳ استلمت راتبك اليوم", description="تعال بكرة تستلم راتبك مرة ثانية 💰", color=0xFF5555)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    user["balance"] += DAILY_AMOUNT
    user["last_daily_date"] = today
    save_json(DATA_FILE, money)

    embed = discord.Embed(title="💰 الراتب اليومي", description=f"### حصلت على {DAILY_AMOUNT} عملة!\nرصيدك الحالي: **{user['balance']}**", color=0xFFD700)
    embed.set_footer(text="تعال بكرة تستلم راتبك مرة ثانية")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="balance", description="عرض رصيدك أو رصيد عضو")
@app_commands.describe(member="العضو (اختياري)")
async def balance(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    user = get_user(member.id)
    await interaction.response.send_message(f"💰 رصيد {member.mention}: {user['balance']}")

@bot.tree.command(name="transfer", description="تحويل فلوس لعضو ثاني")
@app_commands.describe(member="العضو المستلم", amount="المبلغ")
async def transfer(interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[int, 1, None]):
    if member.id == interaction.user.id:
        await interaction.response.send_message("❌ ما تقدر تحول لنفسك.", ephemeral=True)
        return

    sender = get_user(interaction.user.id)
    if sender["balance"] < amount:
        await interaction.response.send_message("❌ رصيدك ما يكفي.", ephemeral=True)
        return

    receiver = get_user(member.id)
    sender["balance"] -= amount
    receiver["balance"] += amount
    save_json(DATA_FILE, money)
    await interaction.response.send_message(f"✅ تم تحويل {amount} عملة إلى {member.mention}")

@bot.tree.command(name="rob", description="حاول تسرق فلوس من عضو ثاني (فيه مخاطرة!)")
@app_commands.describe(member="العضو")
async def rob(interaction: discord.Interaction, member: discord.Member):
    if member.id == interaction.user.id or member.bot:
        await interaction.response.send_message("❌ ما تقدر تسرق هذا العضو.", ephemeral=True)
        return

    thief = get_user(interaction.user.id)
    target = get_user(member.id)

    if target["balance"] < 50:
        await interaction.response.send_message("❌ هذا العضو ما عنده فلوس كافية عشان تسرقه.", ephemeral=True)
        return

    if random.random() < 0.5:
        stolen = random.randint(10, min(200, target["balance"]))
        target["balance"] -= stolen
        thief["balance"] += stolen
        save_json(DATA_FILE, money)
        await interaction.response.send_message(f"🕵️ نجحت! سرقت {stolen} عملة من {member.mention}")
    else:
        fine = random.randint(20, 100)
        thief["balance"] = max(0, thief["balance"] - fine)
        save_json(DATA_FILE, money)
        await interaction.response.send_message(f"🚔 انمسكت! دفعت غرامة {fine} عملة")

@bot.tree.command(name="leaderboard", description="ترتيب أغنى الأعضاء")
async def leaderboard(interaction: discord.Interaction):
    top = sorted(money.items(), key=lambda x: x[1]["balance"], reverse=True)[:10]
    if not top:
        await interaction.response.send_message("لا يوجد بيانات بعد.")
        return

    lines = []
    for i, (uid, data) in enumerate(top, start=1):
        user = interaction.guild.get_member(int(uid))
        name = user.display_name if user else f"عضو ({uid})"
        lines.append(f"**{i}.** {name} — 💰 {data['balance']}")

    embed = discord.Embed(title="🏆 قائمة الأغنياء", description="\n".join(lines), color=0xFFD700)
    await interaction.response.send_message(embed=embed)


# =========================
# 🎮 الألعاب والفعاليات
# =========================
DICE_FACES = ["⚀", "⚁", "⚂", "⚃", "⚄", "⚅"]

@bot.tree.command(name="coin", description="رمي عملة ذهبية")
async def coin(interaction: discord.Interaction):
    result = random.choice(["👑 وجه", "🔠 كتابة"])
    embed = discord.Embed(title="🪙 رمي العملة", description=f"### النتيجة: {result}", color=0xFFD700)
    embed.set_footer(text=f"طلب بواسطة {interaction.user.display_name}")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="dice", description="رمي نرد")
async def dice(interaction: discord.Interaction):
    number = random.randint(1, 6)
    embed = discord.Embed(title="🎲 رمي النرد", description=f"# {DICE_FACES[number - 1]}\n### طلع رقم {number}", color=0x00AAFF)
    embed.set_footer(text=f"طلب بواسطة {interaction.user.display_name}")
    await interaction.response.send_message(embed=embed)

SLOT_EMOJIS = ["🍒", "🍋", "🍇", "🍉", "⭐", "💎", "7️⃣"]
SLOT_PAYOUTS = {"7️⃣": 10, "💎": 8, "⭐": 6, "🍉": 4, "🍇": 3, "🍋": 2, "🍒": 2}

@bot.tree.command(name="slots", description="ماكينة الحظ 🎰 - راهن واربح!")
@app_commands.describe(bet="مبلغ الرهان")
async def slots(interaction: discord.Interaction, bet: app_commands.Range[int, 10, None]):
    user = get_user(interaction.user.id)
    if user["balance"] < bet:
        await interaction.response.send_message("❌ رصيدك ما يكفي لهذا الرهان.", ephemeral=True)
        return

    reels = [random.choice(SLOT_EMOJIS) for _ in range(3)]
    embed = discord.Embed(title="🎰 ماكينة الحظ")
    embed.description = f"# [ {reels[0]} | {reels[1]} | {reels[2]} ]"

    if reels[0] == reels[1] == reels[2]:
        multiplier = SLOT_PAYOUTS[reels[0]]
        winnings = bet * multiplier
        user["balance"] += winnings
        embed.add_field(name="🎉 فزت!", value=f"ربحت **{winnings}** عملة (x{multiplier})", inline=False)
        embed.colour = 0x00FF00
    else:
        user["balance"] -= bet
        embed.add_field(name="💸 خسرت", value=f"خسرت **{bet}** عملة", inline=False)
        embed.colour = 0xFF0000

    save_json(DATA_FILE, money)
    embed.set_footer(text=f"رصيدك الآن: {user['balance']}")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="rps", description="🪨📄✂️ حجرة ورقة مقص ضد البوت")
@app_commands.describe(choice="اختيارك")
@app_commands.choices(choice=[
    app_commands.Choice(name="🪨 حجرة", value="rock"),
    app_commands.Choice(name="📄 ورقة", value="paper"),
    app_commands.Choice(name="✂️ مقص", value="scissors"),
])
async def rps(interaction: discord.Interaction, choice: app_commands.Choice[str]):
    options = {"rock": "🪨 حجرة", "paper": "📄 ورقة", "scissors": "✂️ مقص"}
    bot_choice = random.choice(list(options.keys()))

    if choice.value == bot_choice:
        result, color = "🤝 تعادل!", 0xFFFF00
    elif (
        (choice.value == "rock" and bot_choice == "scissors")
        or (choice.value == "paper" and bot_choice == "rock")
        or (choice.value == "scissors" and bot_choice == "paper")
    ):
        user = get_user(interaction.user.id)
        user["balance"] += 20
        save_json(DATA_FILE, money)
        result, color = "🎉 فزت! (+20 💰)", 0x00FF00
    else:
        result, color = "💀 خسرت!", 0xFF0000

    embed = discord.Embed(title="🪨📄✂️ حجرة ورقة مقص", color=color)
    embed.add_field(name="اختيارك", value=options[choice.value], inline=True)
    embed.add_field(name="اختيار البوت", value=options[bot_choice], inline=True)
    embed.add_field(name="النتيجة", value=result, inline=False)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="wheel", description="🎡 عجلة الحظ - دورها واربح جوائز")
async def wheel(interaction: discord.Interaction):
    prizes = [0, 20, 50, 100, 150, 200, 300, 500]
    weights = [15, 20, 20, 15, 12, 10, 5, 3]
    prize = random.choices(prizes, weights=weights, k=1)[0]

    user = get_user(interaction.user.id)
    user["balance"] += prize
    save_json(DATA_FILE, money)

    embed = discord.Embed(title="🎡 عجلة الحظ", color=0xAA00FF)
    if prize == 0:
        embed.description = "### 😢 للأسف ما ربحت شي هالمرة"
    else:
        embed.description = f"### 🎊 مبروك! ربحت **{prize}** عملة"
    embed.set_footer(text=f"رصيدك الآن: {user['balance']}")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="guess", description="🎯 خمن رقم بين 1 و10 واربح 50 عملة")
@app_commands.describe(number="تخمينك (1-10)")
async def guess(interaction: discord.Interaction, number: app_commands.Range[int, 1, 10]):
    secret = random.randint(1, 10)
    if number == secret:
        user = get_user(interaction.user.id)
        user["balance"] += 50
        save_json(DATA_FILE, money)
        embed = discord.Embed(title="🎯 تخمين صحيح!", description=f"### الرقم كان {secret} 🎉\nربحت **50** عملة", color=0x00FF00)
    else:
        embed = discord.Embed(title="❌ تخمين خاطئ", description=f"### الرقم الصحيح كان {secret}\nحاول مرة ثانية!", color=0xFF0000)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="poll", description="إنشاء تصويت سريع (يس/لا)")
@app_commands.describe(question="السؤال")
async def poll(interaction: discord.Interaction, question: str):
    embed = discord.Embed(title="📊 تصويت", description=question, color=0x00AAFF)
    embed.set_footer(text=f"بواسطة {interaction.user.display_name}")
    await interaction.response.send_message(embed=embed)
    msg = await interaction.original_response()
    await msg.add_reaction("✅")
    await msg.add_reaction("❌")


# =========================
# 🎫 نظام التكتات الاحترافي
# =========================
TICKET_CATEGORIES = [
    ("🎫 دعم عام", "عام", "أي استفسار أو مساعدة عامة"),
    ("💰 صنع سكربت", "سكربتات", "افتح تكت لو حاب تصنع سكربت باسمك"),
    ("⚠️ إبلاغ عن عضو", "إبلاغ", "إبلاغ عن مخالفة أو عضو مسيء"),
    ("🤝 تعاون / شراكة", "شراكة", "طلبات تعاون أو شراكة مع السيرفر"),
    ("✅ وساطة","وسيط", "طلب وسيط لضمن حق الطرفين"),
]

class TicketPanelSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=label, description=desc, value=value)
            for label, value, desc in TICKET_CATEGORIES
        ]
        super().__init__(placeholder="📩 اختر نوع التكت اللي تبي تفتحه...", options=options, custom_id="ticket_panel_select")

    async def callback(self, interaction: discord.Interaction):
        label = next(l for l, v, d in TICKET_CATEGORIES if v == self.values[0])
        await create_ticket(interaction, label)

class TicketPanelView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketPanelSelect())

class TicketControlView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="استلام", emoji="🙋", style=discord.ButtonStyle.blurple, custom_id="ticket_claim")
    async def claim_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = tickets_db.get(str(interaction.channel.id))
        if not data:
            await interaction.response.send_message("❌ هذا مو روم تكت صالح.", ephemeral=True)
            return
        if not is_ticket_staff(interaction.user):
            await interaction.response.send_message("🚫 بس فريق الدعم يقدر يستلم التكت.", ephemeral=True)
            return
        if data.get("claimed_by"):
            claimer = interaction.guild.get_member(data["claimed_by"])
            name = claimer.mention if claimer else "شخص غادر السيرفر"
            await interaction.response.send_message(f"⚠️ التكت مستلم مسبقًا بواسطة {name}.", ephemeral=True)
            return

        data["claimed_by"] = interaction.user.id
        save_json(TICKET_DATA_FILE, tickets_db)

        button.label = f"مستلم بواسطة {interaction.user.display_name}"
        button.emoji = "✅"
        button.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.channel.send(f"🙋 {interaction.user.mention} استلم هذا التكت وراح يساعدك الآن.")

    @discord.ui.button(label="إغلاق التكت", emoji="🔒", style=discord.ButtonStyle.red, custom_id="ticket_close")
    async def close_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = tickets_db.get(str(interaction.channel.id))
        if not data:
            await interaction.response.send_message("❌ هذا مو روم تكت صالح.", ephemeral=True)
            return
        if not (is_ticket_staff(interaction.user) or interaction.user.id == data["owner_id"]):
            await interaction.response.send_message("🚫 ما تقدر تسكر هذا التكت.", ephemeral=True)
            return

        await interaction.response.send_message("🔒 جاري إغلاق التكت وحفظ الترانسكريبت خلال 5 ثواني...")
        await close_ticket(interaction.channel, interaction.user)

async def create_ticket(interaction: discord.Interaction, category_label: str):
    guild = interaction.guild
    await interaction.response.defer(ephemeral=True)

    category_id = ticket_config.get("category_id")
    if not category_id:
        await interaction.followup.send("❌ نظام التكتات غير مُفعّل بعد، خلي الإدارة تسوي `/ticket_setup`.", ephemeral=True)
        return

    category = guild.get_channel(category_id)
    support_role_id = ticket_config.get("support_role_id")
    support_role = guild.get_role(support_role_id) if support_role_id else None

    for data in tickets_db.values():
        if data["owner_id"] == interaction.user.id and data.get("status") == "open":
            existing = guild.get_channel(data.get("channel_id", 0))
            if existing:
                await interaction.followup.send(f"❌ عندك تكت مفتوح فعلاً: {existing.mention}", ephemeral=True)
                return

    ticket_config["counter"] = ticket_config.get("counter", 0) + 1
    number = ticket_config["counter"]
    save_json(TICKET_CONFIG_FILE, ticket_config)

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        interaction.user: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True, attach_files=True
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, manage_channels=True, read_message_history=True
        ),
    }
    if support_role:
        overwrites[support_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

    channel = await guild.create_text_channel(
        name=f"ticket-{number:04d}",
        category=category,
        overwrites=overwrites,
        topic=f"owner:{interaction.user.id}",
        reason=f"تكت جديد بواسطة {interaction.user}",
    )

    tickets_db[str(channel.id)] = {
        "channel_id": channel.id,
        "owner_id": interaction.user.id,
        "claimed_by": None,
        "category": category_label,
        "number": number,
        "status": "open",
    }
    save_json(TICKET_DATA_FILE, tickets_db)

    embed = discord.Embed(
        title=f"🎫 تكت #{number:04d}",
        description=(
            f"مرحبًا {interaction.user.mention} 👋\n\n"
            f"**النوع:** {category_label}\n\n"
            "فريق الدعم راح يوصلك قريب، اشرح مشكلتك أو استفسارك بالتفصيل 📝"
        ),
        color=0x0099FF,
    )
    if support_role:
        embed.add_field(name="🛡️ فريق الدعم", value=support_role.mention, inline=False)
    embed.set_footer(text="استخدم الأزرار تحت للتحكم بالتكت")
    embed.timestamp = discord.utils.utcnow()

    ping = support_role.mention if support_role else ""
    await channel.send(content=f"{interaction.user.mention} {ping}".strip(), embed=embed, view=TicketControlView())
    await interaction.followup.send(f"✅ تم إنشاء تكتك: {channel.mention}", ephemeral=True)

async def close_ticket(channel: discord.TextChannel, closer: discord.abc.User):
    data = tickets_db.get(str(channel.id))
    if not data:
        return

    lines = []
    async for msg in channel.history(limit=None, oldest_first=True):
        time_str = msg.created_at.strftime("%Y-%m-%d %H:%M")
        content = msg.content or "[بدون نص / مرفق]"
        lines.append(f"[{time_str}] {msg.author}: {content}")

    transcript_text = "\n".join(lines) if lines else "لا توجد رسائل."

    log_channel_id = ticket_config.get("log_channel_id")
    if log_channel_id:
        log_channel = channel.guild.get_channel(log_channel_id)
        if log_channel:
            buffer = io.BytesIO(transcript_text.encode("utf-8"))
            file = discord.File(buffer, filename=f"transcript-{channel.name}.txt")

            embed = discord.Embed(title=f"📁 أُغلق تكت #{data['number']:04d}", color=0xFF5555)
            embed.add_field(name="👤 صاحب التكت", value=f"<@{data['owner_id']}>", inline=True)
            embed.add_field(name="🔒 أغلقه", value=closer.mention, inline=True)
            claimer = f"<@{data['claimed_by']}>" if data.get("claimed_by") else "لم يُستلم"
            embed.add_field(name="🙋 مستلم بواسطة", value=claimer, inline=True)
            embed.timestamp = discord.utils.utcnow()

            try:
                await log_channel.send(embed=embed, file=file)
            except Exception:
                pass

    tickets_db.pop(str(channel.id), None)
    save_json(TICKET_DATA_FILE, tickets_db)

    await asyncio.sleep(5)
    try:
        await channel.delete(reason=f"تم إغلاق التكت بواسطة {closer}")
    except Exception:
        pass

@bot.tree.command(name="ticket_setup", description="إعداد نظام التكتات")
@is_allowed_role()
@app_commands.describe(category="الكاتيقوري اللي تُفتح فيها التكتات", support_role="رول فريق الدعم", log_channel="روم حفظ الترانسكريبت (اختياري)")
async def ticket_setup(
    interaction: discord.Interaction,
    category: discord.CategoryChannel,
    support_role: discord.Role,
    log_channel: discord.TextChannel = None,
):
    ticket_config["category_id"] = category.id
    ticket_config["support_role_id"] = support_role.id
    ticket_config["log_channel_id"] = log_channel.id if log_channel else None
    save_json(TICKET_CONFIG_FILE, ticket_config)

    embed = discord.Embed(title="✅ تم إعداد نظام التكتات", color=0x00FF00)
    embed.add_field(name="📁 الكاتيقوري", value=category.mention, inline=True)
    embed.add_field(name="🛡️ رول الدعم", value=support_role.mention, inline=True)
    embed.add_field(name="📜 روم اللوق", value=log_channel.mention if log_channel else "غير محدد", inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="ticket_panel", description="إرسال لوحة فتح التكتات في هذا الروم")
@is_allowed_role()
@app_commands.describe(title="عنوان اللوحة (اختياري)", description="وصف اللوحة (اختياري)")
async def ticket_panel_cmd(
    interaction: discord.Interaction,
    title: str = "🎫 مركز الدعم والتكتات",
    description: str = "اختر نوع التكت من القائمة تحت 👇 وراح يفتح لك روم خاص مع فريقنا.",
):
    if not ticket_config.get("category_id"):
        await interaction.response.send_message("❌ لازم تسوي `/ticket_setup` أول.", ephemeral=True)
        return

    embed = discord.Embed(title=title, description=description, color=0x0099FF)
    embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)
    embed.set_footer(text="فريق الدعم متواجد لمساعدتك 24/7")
    await interaction.response.send_message(embed=embed, view=TicketPanelView())

@bot.tree.command(name="ticket_add", description="إضافة عضو للتكت الحالي")
@app_commands.describe(member="العضو المراد إضافته")
async def ticket_add(interaction: discord.Interaction, member: discord.Member):
    data = tickets_db.get(str(interaction.channel.id))
    if not data:
        await interaction.response.send_message("❌ هذا الأمر يشتغل بس داخل روم تكت.", ephemeral=True)
        return
    if not is_ticket_staff(interaction.user):
        await interaction.response.send_message("🚫 بس فريق الدعم يقدر يضيف أعضاء.", ephemeral=True)
        return

    await interaction.channel.set_permissions(member, view_channel=True, send_messages=True, read_message_history=True)
    await interaction.response.send_message(f"✅ تم إضافة {member.mention} للتكت.")

@bot.tree.command(name="ticket_remove", description="إزالة عضو من التكت الحالي")
@app_commands.describe(member="العضو المراد إزالته")
async def ticket_remove(interaction: discord.Interaction, member: discord.Member):
    data = tickets_db.get(str(interaction.channel.id))
    if not data:
        await interaction.response.send_message("❌ هذا الأمر يشتغل بس داخل روم تكت.", ephemeral=True)
        return
    if not is_ticket_staff(interaction.user):
        await interaction.response.send_message("🚫 بس فريق الدعم يقدر يزيل أعضاء.", ephemeral=True)
        return
    if member.id == data["owner_id"]:
        await interaction.response.send_message("❌ ما تقدر تشيل صاحب التكت.", ephemeral=True)
        return

    await interaction.channel.set_permissions(member, overwrite=None)
    await interaction.response.send_message(f"✅ تم إزالة {member.mention} من التكت.")

@bot.tree.command(name="ticket_rename", description="تغيير اسم التكت الحالي")
@app_commands.describe(new_name="الاسم الجديد")
async def ticket_rename(interaction: discord.Interaction, new_name: str):
    data = tickets_db.get(str(interaction.channel.id))
    if not data:
        await interaction.response.send_message("❌ هذا الأمر يشتغل بس داخل روم تكت.", ephemeral=True)
        return
    if not is_ticket_staff(interaction.user):
        await interaction.response.send_message("🚫 بس فريق الدعم يقدر يغير الاسم.", ephemeral=True)
        return

    await interaction.channel.edit(name=f"ticket-{new_name}")
    await interaction.response.send_message(f"✅ تم تغيير اسم التكت إلى `ticket-{new_name}`")

@bot.tree.command(name="ticket_close", description="إغلاق التكت الحالي يدويًا")
async def ticket_close_cmd(interaction: discord.Interaction):
    data = tickets_db.get(str(interaction.channel.id))
    if not data:
        await interaction.response.send_message("❌ هذا الأمر يشتغل بس داخل روم تكت.", ephemeral=True)
        return
    if not (is_ticket_staff(interaction.user) or interaction.user.id == data["owner_id"]):
        await interaction.response.send_message("🚫 ما تقدر تسكر هذا التكت.", ephemeral=True)
        return

    await interaction.response.send_message("🔒 جاري إغلاق التكت وحفظ الترانسكريبت خلال 5 ثواني...")
    await close_ticket(interaction.channel, interaction.user)


# =========================
# ⚡ الأدوات العامة
# =========================
@bot.tree.command(name="ping", description="عرض سرعة استجابة البوت")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(f"🏓 {round(bot.latency * 1000)}ms")

@bot.tree.command(name="help", description="عرض كل أوامر البوت")
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(title="📖 قائمة الأوامر", color=0x00FF99)
    embed.add_field(
        name=f"🔨 الإدارة (رول {ALLOWED_ROLE_NAME} فقط)",
        value="`/kick` `/ban` `/unban` `/mute` `/unmute` `/warn` `/warnings` `/clear_warnings`\n"
              "`/clear` `/clear_images` `/clear_user` `/clr` `/noformrbeast` `/remove_banroom`\n"
              "`/say` `/say_embed` `/script` `/add_role` `/remove_role` `/lock` `/unlock` `/add_money` `/remove_money`",
        inline=False,
    )
    embed.add_field(name="💰 الاقتصاد", value="`/daily` `/balance` `/transfer` `/rob` `/leaderboard`", inline=False)
    embed.add_field(name="ℹ️ معلومات", value="`/userinfo` `/serverinfo` `/avatar` `/ping`", inline=False)
    embed.add_field(name="🎮 تسلية", value="`/coin` `/dice` `/slots` `/rps` `/wheel` `/guess` `/poll`", inline=False)
    embed.add_field(name="🎫 التكتات", value="`/ticket_setup` `/ticket_panel` `/ticket_add` `/ticket_remove` `/ticket_rename` `/ticket_close`", inline=False)
    await interaction.response.send_message(embed=embed)


# =========================
# 🚀 بداية تشغيل البوت
# =========================
@bot.event
async def on_ready():
    print(f"🔥 تم تسجيل الدخول باسم {bot.user}")
    bot.add_view(TicketPanelView())
    bot.add_view(TicketControlView())
    await bot.tree.sync()
