import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.types import ContentType
from aiogram.utils import executor
from datetime import datetime

API_TOKEN = "YOUR_BOT_TOKEN"

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# ================= DATA =================
admins = [111111111, 222222222]  # your admin IDs
admin_status = {admin: False for admin in admins}
users = {}
tickets = {}
ticket_counter = 1

notify_all_mode = set()
notify_user_mode = {}
schedule_mode = {}
scheduled_notifications = []

# ================= HELPERS =================
def generate_ticket():
    global ticket_counter
    ticket_id = f"#{ticket_counter:03d}"
    ticket_counter += 1
    return ticket_id

def get_least_busy_admin():
    load = {admin: 0 for admin in admins}
    for u in users.values():
        load[u["admin"]] += 1

    return min(load, key=load.get)

# ================= START =================
@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    user_id = message.from_user.id

    if user_id not in users:
        admin = get_least_busy_admin()
        ticket_id = generate_ticket()

        users[user_id] = {"admin": admin, "ticket": ticket_id}
        tickets[ticket_id] = user_id

        await bot.send_message(admin, f"🆕 New Ticket {ticket_id}\nUser: {user_id}")

    await message.reply("✅ You are connected to support")

# ================= USER MESSAGE =================
@dp.message_handler(lambda m: m.from_user.id not in admins, content_types=ContentType.ANY)
async def user_message(message: types.Message):
    user_id = message.from_user.id

    if user_id not in users:
        return

    admin = users[user_id]["admin"]
    ticket = users[user_id]["ticket"]

    await bot.copy_message(admin, user_id, message.message_id)
    await bot.send_message(admin, f"📩 Ticket {ticket}")

# ================= ADMIN REPLY =================
@dp.message_handler(lambda m: m.from_user.id in admins, content_types=ContentType.ANY)
async def admin_reply(message: types.Message):
    if not message.reply_to_message:
        return

    try:
        user_id = message.reply_to_message.forward_from.id
    except:
        return

    await bot.copy_message(user_id, message.chat.id, message.message_id)

# ================= ADMIN ONLINE =================
@dp.message_handler(commands=['online'])
async def admin_online(message: types.Message):
    if message.from_user.id in admins:
        admin_status[message.from_user.id] = True
        await message.reply("🟢 You are ONLINE")

@dp.message_handler(commands=['offline'])
async def admin_offline(message: types.Message):
    if message.from_user.id in admins:
        admin_status[message.from_user.id] = False
        await message.reply("🔴 You are OFFLINE")

# ================= DASHBOARD =================
@dp.message_handler(commands=['dashboard'])
async def dashboard(message: types.Message):
    if message.from_user.id not in admins:
        return

    total_users = len(users)
    total_tickets = len(tickets)

    load = {admin: 0 for admin in admins}
    for u in users.values():
        load[u["admin"]] += 1

    text = f"📊 DASHBOARD\n\nUsers: {total_users}\nTickets: {total_tickets}\n\n"

    for admin in admins:
        status = "🟢" if admin_status[admin] else "🔴"
        text += f"{status} {admin} → {load[admin]} users\n"

    await message.reply(text)

# ================= TRANSFER =================
@dp.message_handler(commands=['transfer'])
async def transfer(message: types.Message):
    if message.from_user.id not in admins:
        return

    try:
        _, user_id, new_admin = message.text.split()
        user_id = int(user_id)
        new_admin = int(new_admin)

        old_admin = users[user_id]["admin"]
        users[user_id]["admin"] = new_admin

        await bot.send_message(old_admin, f"🔄 User {user_id} transferred")
        await bot.send_message(new_admin, f"📥 New user assigned: {user_id}")
        await bot.send_message(user_id, "🔄 Your support admin changed")

    except:
        await message.reply("Usage: /transfer user_id new_admin_id")

# ================= NOTIFY =================
@dp.message_handler(commands=['notify'])
async def notify_all(message: types.Message):
    if message.from_user.id in admins:
        notify_all_mode.add(message.from_user.id)
        await message.reply("Send notification")

@dp.message_handler(commands=['notify_user'])
async def notify_user(message: types.Message):
    if message.from_user.id in admins:
        try:
            _, uid = message.text.split()
            notify_user_mode[message.from_user.id] = int(uid)
            await message.reply("Send message")
        except:
            await message.reply("Usage: /notify_user user_id")

@dp.message_handler(commands=['schedule'])
async def schedule(message: types.Message):
    if message.from_user.id in admins:
        schedule_mode[message.from_user.id] = {"step": "time"}
        await message.reply("Send time HH:MM")

# ================= MAIN HANDLER =================
@dp.message_handler(content_types=ContentType.ANY)
async def main_handler(message: types.Message):
    uid = message.from_user.id

    # notify all
    if uid in notify_all_mode:
        for u in users:
            try:
                await bot.copy_message(u, message.chat.id, message.message_id)
            except:
                pass

        notify_all_mode.remove(uid)
        await message.reply("✅ Sent to all")
        return

    # notify user
    if uid in notify_user_mode:
        target = notify_user_mode[uid]

        try:
            await bot.copy_message(target, message.chat.id, message.message_id)
            await message.reply("✅ Sent")
        except:
            await message.reply("❌ Failed")

        del notify_user_mode[uid]
        return

    # schedule
    if uid in schedule_mode:
        step = schedule_mode[uid]["step"]

        if step == "time":
            schedule_mode[uid]["time"] = message.text
            schedule_mode[uid]["step"] = "content"
            await message.reply("Send content")
            return

        elif step == "content":
            scheduled_notifications.append({
                "time": schedule_mode[uid]["time"],
                "chat_id": message.chat.id,
                "message_id": message.message_id
            })

            del schedule_mode[uid]
            await message.reply("✅ Scheduled")
            return

# ================= SCHEDULER =================
async def scheduler():
    while True:
        now = datetime.now().strftime("%H:%M")

        for note in scheduled_notifications[:]:
            if note["time"] == now:
                for u in users:
                    try:
                        await bot.copy_message(
                            u,
                            note["chat_id"],
                            note["message_id"]
                        )
                    except:
                        pass

                scheduled_notifications.remove(note)

        await asyncio.sleep(30)

# ================= RUN =================
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(scheduler())
    executor.start_polling(dp, skip_updates=True)is         c.execute("""
        CREATE TABLE IF NOT EXISTS members (
            user_id INTEGER PRIMARY KEY,
            assigned_leader INTEGER,
            full_name TEXT
        )""")
        c.execute("""
        CREATE TABLE IF NOT EXISTS leader_status (
            leader_id INTEGER PRIMARY KEY,
            is_online INTEGER DEFAULT 1
        )""")
        c.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid INTEGER,
            leader_id INTEGER,
            kind TEXT,      -- 'message' or 'prayer_request'
            msg TEXT
        )""")
        c.execute("""
        CREATE TABLE IF NOT EXISTS resources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id TEXT,
            name TEXT,
            cat TEXT        -- 'sermons', 'devotionals', 'hymns'
        )""")

        for lid in LEADER_IDS:
            c.execute(
                "INSERT OR IGNORE INTO leader_status (leader_id,is_online) VALUES (?,1)",
                (lid,)
            )

def get_assigned_leader(uid):
    with sqlite3.connect("bot_data.db") as conn:
        r = conn.execute(
            "SELECT assigned_leader FROM members WHERE user_id=?",
            (uid,)
        ).fetchone()
    return r[0] if r and r[0] else None

# ----------------------------
# MENUS
# ----------------------------
MAIN_MENU = ReplyKeyboardMarkup(
    [
        ["💬 Talk to a Fellowship Leader", "🙏 Prayer Request"],
        ["📖 Resources", "🔄 Request Another Leader"],
        [KeyboardButton("🖥️ Open Church App", web_app=WebAppInfo(url=WEBAPP_URL))],
    ],
    resize_keyboard=True
)

RESOURCE_MENU = ReplyKeyboardMarkup(
    [["🎙️ Sermons", "📅 Devotionals"], ["🎵 Hymns", "🔙 Back"]],
    resize_keyboard=True
)

# ----------------------------
# START
# ----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if uid in LEADER_IDS:
        await update.message.reply_text(
            "✝️ Fellowship Leader Mode Active.\n"
            "Commands:\n"
            "/track <user_id> - See a member's message history\n"
            "/ticket <number> - Reply to a member's message"
        )
        return

    with sqlite3.connect("bot_data.db") as conn:
        conn.execute(
            "INSERT OR IGNORE INTO members (user_id, full_name) VALUES (?, ?)",
            (uid, update.effective_user.full_name)
        )

    await update.message.reply_text(
        "Welcome to our church fellowship bot! 🙏\n"
        "You can chat with a fellowship leader, submit a prayer request, "
        "browse resources, or open the church app below.",
        reply_markup=MAIN_MENU
    )

# ----------------------------
# CENTRAL MESSAGE ROUTER
# ----------------------------
async def central_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Decides whether the message is a leader replying to a ticket,
    or a member using the menu / chatting.
    """
    uid = update.effective_user.id

    if uid in LEADER_IDS:
        if "reply_uid" in context.user_data:
            await leader_text_reply(update, context)
        else:
            await update.message.reply_text("Leader: use /ticket <number> to start a reply.")
        return

    await member_logic(update, context)

# ----------------------------
# WEB APP DATA HANDLER
# (fires when the Mini App calls Telegram.WebApp.sendData(...))
# ----------------------------
async def handle_webapp_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        data = json.loads(update.effective_message.web_app_data.data)
        text = data.get("text", "").strip()
        kind = data.get("type", "message")
    except (json.JSONDecodeError, AttributeError):
        await update.message.reply_text("⚠️ Couldn't read that submission, please try again.")
        return

    if not text:
        await update.message.reply_text("⚠️ Empty submission — nothing sent.")
        return

    await route_to_leader(update, context, text, kind=kind)

# ----------------------------
# MEMBER LOGIC
# ----------------------------
async def member_logic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text

    # --- RESOURCES ---
    if text == "📖 Resources":
        await update.message.reply_text("Select a category:", reply_markup=RESOURCE_MENU)
        return

    if text in ["🎙️ Sermons", "📅 Devotionals", "🎵 Hymns", "🔙 Back"]:
        await send_resource_content(update, context)
        return

    # --- PRAYER REQUEST (typed flow, separate from the Mini App form) ---
    if text == "🙏 Prayer Request":
        context.user_data["awaiting_prayer"] = True
        await update.message.reply_text(
            "Please share your prayer request. It will be sent privately to a fellowship leader."
        )
        return

    if context.user_data.get("awaiting_prayer"):
        context.user_data.pop("awaiting_prayer")
        await route_to_leader(update, context, text, kind="prayer_request")
        return

    # --- TRANSFER LEADER ---
    if text == "🔄 Request Another Leader":
        old = get_assigned_leader(uid)
        available = [l for l in LEADER_IDS if l != old]
        new = random.choice(available) if available else random.choice(LEADER_IDS)

        with sqlite3.connect("bot_data.db") as conn:
            conn.execute(
                "UPDATE members SET assigned_leader=? WHERE user_id=?",
                (new, uid)
            )

        if old:
            try:
                await context.bot.send_message(old, f"⚠️ Member {uid} was reassigned.")
            except Exception:
                pass

        try:
            await context.bot.send_message(new, f"📌 New member assigned: {uid}")
        except Exception:
            pass

        await update.message.reply_text("You're now connected with a new fellowship leader.")
        return

    # --- TALK TO A LEADER (regular chat message) ---
    if text == "💬 Talk to a Fellowship Leader":
        await update.message.reply_text("Go ahead, type your message and I'll pass it along.")
        return

    # Anything else typed = a regular message to the assigned leader
    await route_to_leader(update, context, text, kind="message")

async def route_to_leader(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, kind: str):
    uid = update.effective_user.id

    leader_id = get_assigned_leader(uid)
    if not leader_id:
        leader_id = random.choice(LEADER_IDS)
        with sqlite3.connect("bot_data.db") as conn:
            conn.execute(
                "UPDATE members SET assigned_leader=? WHERE user_id=?",
                (leader_id, uid)
            )

    with sqlite3.connect("bot_data.db") as conn:
        conn.execute(
            "INSERT INTO tickets (uid, leader_id, kind, msg) VALUES (?,?,?,?)",
            (uid, leader_id, kind, text)
        )

    lst = LEADER_LAST_TICKETS.setdefault(leader_id, [])
    lst.append(uid)
    index = len(lst)

    label = "🙏 Prayer Request" if kind == "prayer_request" else "📥 Message"

    try:
        await context.bot.send_message(
            leader_id,
            f"{label} #{index}\nFrom member {uid}:\n{text}\n\nReply: /ticket {index}"
        )
        await update.message.reply_text("✅ Sent. A fellowship leader will follow up with you.")
    except Exception:
        await update.message.reply_text("Saved, but the leader appears to be offline right now.")

# ----------------------------
# RESOURCE HELPER
# ----------------------------
async def send_resource_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    uid = update.effective_user.id
    cat_map = {"🎙️ Sermons": "sermons", "📅 Devotionals": "devotionals", "🎵 Hymns": "hymns"}

    if text == "🔙 Back":
        await update.message.reply_text("Back to the main menu.", reply_markup=MAIN_MENU)
        return

    if text not in cat_map:
        return

    with sqlite3.connect("bot_data.db") as conn:
        rows = conn.execute(
            "SELECT file_id, name FROM resources WHERE cat=?",
            (cat_map[text],)
        ).fetchall()

    if not rows:
        await update.message.reply_text("No resources uploaded in this category yet.")
        return

    for file_id, name in rows:
        try:
            await context.bot.send_document(uid, file_id, caption=name)
        except Exception:
            pass

# ----------------------------
# LEADER LOGIC
# ----------------------------
async def reply_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    leader_id = update.effective_user.id
    if leader_id not in LEADER_IDS:
        return

    try:
        ticket_num = int(context.args[0])
        target_uid = LEADER_LAST_TICKETS[leader_id][ticket_num - 1]
        context.user_data["reply_uid"] = target_uid
        await update.message.reply_text(f"Replying to member {target_uid}. Type your message now:")
    except (IndexError, ValueError, KeyError):
        await update.message.reply_text("Invalid ticket number. Check the list.")

async def leader_text_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = context.user_data.pop("reply_uid")
    text = update.message.text

    try:
        await context.bot.send_message(uid, f"✝️ Fellowship Leader:\n{text}")
        await update.message.reply_text("✅ Reply sent.")
    except Exception:
        await update.message.reply_text("❌ Failed to send. The member may have blocked the bot.")

async def track_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in LEADER_IDS:
        return
    try:
        uid = int(context.args[0])
        with sqlite3.connect("bot_data.db") as conn:
            rows = conn.execute(
                "SELECT kind, msg FROM tickets WHERE uid=? ORDER BY id", (uid,)
            ).fetchall()

        txt = "\n".join(f"{i+1}. [{k}] {m}" for i, (k, m) in enumerate(rows))
        await update.message.reply_text(f"📜 History for {uid}:\n{txt}" if txt else "No history.")
    except Exception:
        await update.message.reply_text("Usage: /track <user_id>")

# ----------------------------
# SET THE MENU BUTTON PROGRAMMATICALLY TOO (redundant with BotFather, harmless to keep)
# ----------------------------
async def post_init(application):
    await application.bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(text="Church App", web_app=WebAppInfo(url=WEBAPP_URL))
    )

# ----------------------------
# RUN
# ----------------------------
init_db()

app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("ticket", reply_ticket))
app.add_handler(CommandHandler("track", track_member))
app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_webapp_data))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, central_message_handler))

print("Church fellowship bot is running...")
app.run_polling()
