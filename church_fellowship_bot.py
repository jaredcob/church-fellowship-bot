import json
import sqlite3
import random
import os
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    WebAppInfo,
    MenuButtonWebApp,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# ----------------------------
# CONFIG
# ----------------------------
TOKEN = os.environ["BOT_TOKEN"]        # <--- set as an environment variable, never hardcode this
LEADER_IDS = [6555910081, 8399604250]  # <--- Telegram user_ids of pastors / elders / fellowship leaders

# Your live Mini App (Cloudflare Pages)
WEBAPP_URL = "https://church-app.yared6594.workers.dev"

# ----------------------------
# DATABASE
# ----------------------------
def init_db():
    with sqlite3.connect("bot_data.db") as conn:
        c = conn.cursor()
        c.execute("""
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
            kind TEXT,
            msg TEXT,
            status TEXT DEFAULT 'open'
        )""")
        c.execute("""
        CREATE TABLE IF NOT EXISTS resources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id TEXT,
            file_type TEXT,
            name TEXT,
            cat TEXT
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

def get_all_member_ids():
    with sqlite3.connect("bot_data.db") as conn:
        rows = conn.execute("SELECT user_id FROM members").fetchall()
    return [r[0] for r in rows]

def get_ticket(ticket_id):
    with sqlite3.connect("bot_data.db") as conn:
        r = conn.execute(
            "SELECT uid, leader_id FROM tickets WHERE id=?",
            (ticket_id,)
        ).fetchone()
    return r

# ----------------------------
# MENUS
# ----------------------------
MAIN_MENU = ReplyKeyboardMarkup(
    [
        ["ðŸ’¬ Talk to a Fellowship Leader", "ðŸ™ Prayer Request"],
        ["ðŸ“– Resources", "ðŸ”„ Request Another Leader"],
        [KeyboardButton("ðŸ–¥ï¸ Open Church App", web_app=WebAppInfo(url=WEBAPP_URL))],
    ],
    resize_keyboard=True
)

RESOURCE_MENU = ReplyKeyboardMarkup(
    [["ðŸŽ™ï¸ Sermons", "ðŸ“… Devotionals"], ["ðŸŽµ Hymns", "ðŸ”™ Back"]],
    resize_keyboard=True
)

# ----------------------------
# START
# ----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if uid in LEADER_IDS:
        await update.message.reply_text(
            "âœï¸ Fellowship Leader Mode Active.\n\n"
            "Commands:\n"
            "/track <user_id> - See a member's message history\n"
            "/ticket <number> - Reply to a member's message (text, photo, voice, or file)\n"
            "/transfer <user_id> <leader_id> - Move a member to another leader\n"
            "/broadcast <message> - Send a message to every member\n"
            "/addsermon - Next photo/voice/file you send is saved as a Sermon resource\n"
            "/adddevotional - Same, saved as a Devotional\n"
            "/addhymn - Same, saved as a Hymn"
        )
        return

    with sqlite3.connect("bot_data.db") as conn:
        conn.execute(
            "INSERT OR IGNORE INTO members (user_id, full_name) VALUES (?, ?)",
            (uid, update.effective_user.full_name)
        )

    await update.message.reply_text(
        "Welcome to our church fellowship bot! ðŸ™\n"
        "You can chat with a fellowship leader, submit a prayer request, "
        "browse resources, or open the church app below.",
        reply_markup=MAIN_MENU
    )

# ----------------------------
# CENTRAL TEXT ROUTER
# ----------------------------
async def central_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if uid in LEADER_IDS:
        if "reply_uid" in context.user_data:
            await leader_text_reply(update, context)
        else:
            await update.message.reply_text("Leader: use /ticket <number> to start a reply.")
        return

    await member_logic(update, context)

# ----------------------------
# MEDIA ROUTER (photo / voice / document)
# ----------------------------
async def media_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    msg = update.message

    if msg.photo:
        file_id, file_type = msg.photo[-1].file_id, "photo"
    elif msg.voice:
        file_id, file_type = msg.voice.file_id, "voice"
    elif msg.document:
        file_id, file_type = msg.document.file_id, "document"
    else:
        return

    caption = msg.caption or ""

    if uid in LEADER_IDS:
        cat = context.user_data.pop("awaiting_resource_cat", None)
        if cat:
            with sqlite3.connect("bot_data.db") as conn:
                conn.execute(
                    "INSERT INTO resources (file_id, file_type, name, cat) VALUES (?,?,?,?)",
                    (file_id, file_type, caption or f"{cat[:-1].capitalize()}", cat)
                )
            await msg.reply_text(f"âœ… Saved to {cat.capitalize()}.")
            return

        if "reply_uid" in context.user_data:
            target_uid = context.user_data.pop("reply_uid")
            try:
                await send_media(context, target_uid, file_type, file_id, caption="âœï¸ Fellowship Leader")
                await msg.reply_text("âœ… Reply sent.")
            except Exception:
                await msg.reply_text("âŒ Failed to send. The member may have blocked the bot.")
            return

        await msg.reply_text(
            "To reply with a file, use /ticket <number> first.\n"
            "To upload a resource, use /addsermon, /adddevotional, or /addhymn first."
        )
        return

    await route_to_leader(update, context, caption or f"[{file_type}]", kind=file_type, file_id=file_id, file_type=file_type)

async def send_media(context, chat_id, file_type, file_id, caption=None):
    if file_type == "photo":
        await context.bot.send_photo(chat_id, file_id, caption=caption)
    elif file_type == "voice":
        await context.bot.send_voice(chat_id, file_id, caption=caption)
    else:
        await context.bot.send_document(chat_id, file_id, caption=caption)

# ----------------------------
# WEB APP DATA HANDLER
# ----------------------------
async def handle_webapp_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        data = json.loads(update.effective_message.web_app_data.data)
        text = data.get("text", "").strip()
        kind = data.get("type", "message")
    except (json.JSONDecodeError, AttributeError):
        await update.message.reply_text("âš ï¸ Couldn't read that submission, please try again.")
        return

    if not text:
        await update.message.reply_text("âš ï¸ Empty submission â€” nothing sent.")
        return

    await route_to_leader(update, context, text, kind=kind)

# ----------------------------
# MEMBER LOGIC
# ----------------------------
async def member_logic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text

    if text == "ðŸ“– Resources":
        await update.message.reply_text("Select a category:", reply_markup=RESOURCE_MENU)
        return

    if text in ["ðŸŽ™ï¸ Sermons", "ðŸ“… Devotionals", "ðŸŽµ Hymns", "ðŸ”™ Back"]:
        await send_resource_content(update, context)
        return

    if text == "ðŸ™ Prayer Request":
        context.user_data["awaiting_prayer"] = True
        await update.message.reply_text(
            "Please share your prayer request. It will be sent privately to a fellowship leader."
        )
        return

    if context.user_data.get("awaiting_prayer"):
        context.user_data.pop("awaiting_prayer")
        await route_to_leader(update, context, text, kind="prayer_request")
        return

    if text == "ðŸ”„ Request Another Leader":
        old = get_assigned_leader(uid)
        available = [l for l in LEADER_IDS if l != old]
        new = random.choice(available) if available else random.choice(LEADER_IDS)

        with sqlite3.connect("bot_data.db") as conn:
            conn.execute("UPDATE members SET assigned_leader=? WHERE user_id=?", (new, uid))

        if old:
            try:
                await context.bot.send_message(old, f"âš ï¸ Member {uid} was reassigned.")
            except Exception:
                pass
        try:
            await context.bot.send_message(new, f"ðŸ“Œ New member assigned: {uid}")
        except Exception:
            pass

        await update.message.reply_text("You're now connected with a new fellowship leader.")
        return

    if text == "ðŸ’¬ Talk to a Fellowship Leader":
        await update.message.reply_text("Go ahead, type your message and I'll pass it along.")
        return

    await route_to_leader(update, context, text, kind="message")

async def route_to_leader(update, context, text, kind, file_id=None, file_type=None):
    uid = update.effective_user.id

    leader_id = get_assigned_leader(uid)
    if not leader_id:
        leader_id = random.choice(LEADER_IDS)
        with sqlite3.connect("bot_data.db") as conn:
            conn.execute("UPDATE members SET assigned_leader=? WHERE user_id=?", (leader_id, uid))

    with sqlite3.connect("bot_data.db") as conn:
        cur = conn.execute(
            "INSERT INTO tickets (uid, leader_id, kind, msg) VALUES (?,?,?,?)",
            (uid, leader_id, kind, text)
        )
        ticket_id = cur.lastrowid

    labels = {
        "prayer_request": "ðŸ™ Prayer Request",
        "photo": "ðŸ–¼ï¸ Photo",
        "voice": "ðŸŽ¤ Voice message",
        "document": "ðŸ“Ž File",
    }
    label = labels.get(kind, "ðŸ“¥ Message")

    try:
        if file_id:
            await send_media(
                context, leader_id, file_type, file_id,
                caption=f"{label} #{ticket_id}\nFrom member {uid}:\n{text}\n\nReply: /ticket {ticket_id}"
            )
        else:
            await context.bot.send_message(
                leader_id,
                f"{label} #{ticket_id}\nFrom member {uid}:\n{text}\n\nReply: /ticket {ticket_id}"
            )
        await update.message.reply_text("âœ… Sent. A fellowship leader will follow up with you.")
    except Exception:
        await update.message.reply_text("Saved, but the leader appears to be offline right now.")

# ----------------------------
# RESOURCE HELPER (member browsing)
# ----------------------------
async def send_resource_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    uid = update.effective_user.id
    cat_map = {"ðŸŽ™ï¸ Sermons": "sermons", "ðŸ“… Devotionals": "devotionals", "ðŸŽµ Hymns": "hymns"}

    if text == "ðŸ”™ Back":
        await update.message.reply_text("Back to the main menu.", reply_markup=MAIN_MENU)
        return

    if text not in cat_map:
        return

    with sqlite3.connect("bot_data.db") as conn:
        rows = conn.execute(
            "SELECT file_id, file_type, name FROM resources WHERE cat=?",
            (cat_map[text],)
        ).fetchall()

    if not rows:
        await update.message.reply_text("No resources uploaded in this category yet.")
        return

    for file_id, file_type, name in rows:
        try:
            await send_media(context, uid, file_type, file_id, caption=name)
        except Exception:
            pass

# ----------------------------
# LEADER: TICKET REPLY
# ----------------------------
async def reply_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    leader_id = update.effective_user.id
    if leader_id not in LEADER_IDS:
        return

    try:
        ticket_id = int(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /ticket <number>")
        return

    ticket = get_ticket(ticket_id)
    if not ticket:
        await update.message.reply_text("Ticket not found. Check the number and try again.")
        return

    target_uid, _ = ticket
    context.user_data["reply_uid"] = target_uid
    await update.message.reply_text(
        f"Replying to member {target_uid}. Send text, a photo, a voice note, or a file now:"
    )

async def leader_text_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = context.user_data.pop("reply_uid")
    text = update.message.text

    try:
        await context.bot.send_message(uid, f"âœï¸ Fellowship Leader:\n{text}")
        await update.message.reply_text("âœ… Reply sent.")
    except Exception:
        await update.message.reply_text("âŒ Failed to send. The member may have blocked the bot.")

# ----------------------------
# LEADER: /transfer <user_id> <leader_id>
# ----------------------------
async def transfer_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    acting_leader = update.effective_user.id
    if acting_leader not in LEADER_IDS:
        return

    try:
        target_uid = int(context.args[0])
        new_leader = int(context.args[1])
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /transfer <user_id> <new_leader_id>")
        return

    if new_leader not in LEADER_IDS:
        await update.message.reply_text("That leader ID isn't recognized.")
        return

    old_leader = get_assigned_leader(target_uid)

    with sqlite3.connect("bot_data.db") as conn:
        conn.execute("UPDATE members SET assigned_leader=? WHERE user_id=?", (new_leader, target_uid))

    try:
        await context.bot.send_message(
            target_uid, "ðŸ”„ You've been transferred to a new fellowship leader. They'll be in touch."
        )
    except Exception:
        pass

    if old_leader and old_leader != new_leader:
        try:
            await context.bot.send_message(old_leader, f"âš ï¸ Member {target_uid} was transferred to another leader.")
        except Exception:
            pass

    try:
        await context.bot.send_message(new_leader, f"ðŸ“Œ Member {target_uid} was transferred to you.")
    except Exception:
        pass

    await update.message.reply_text(f"âœ… Member {target_uid} transferred to leader {new_leader}.")

# ----------------------------
# LEADER: /broadcast <message>
# ----------------------------
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in LEADER_IDS:
        return

    text = " ".join(context.args)
    if not text:
        await update.message.reply_text("Usage: /broadcast <message>")
        return

    member_ids = get_all_member_ids()
    sent, failed = 0, 0
    for mid in member_ids:
        try:
            await context.bot.send_message(mid, f"ðŸ“¢ Announcement:\n{text}")
            sent += 1
        except Exception:
            failed += 1

    await update.message.reply_text(f"âœ… Broadcast sent to {sent} members. ({failed} failed/blocked.)")

# ----------------------------
# LEADER: resource upload flow
# ----------------------------
async def addsermon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in LEADER_IDS:
        return
    context.user_data["awaiting_resource_cat"] = "sermons"
    await update.message.reply_text("Send the sermon now â€” as a photo, voice note, or file.")

async def adddevotional(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in LEADER_IDS:
        return
    context.user_data["awaiting_resource_cat"] = "devotionals"
    await update.message.reply_text("Send the devotional now â€” as a photo, voice note, or file.")

async def addhymn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in LEADER_IDS:
        return
    context.user_data["awaiting_resource_cat"] = "hymns"
    await update.message.reply_text("Send the hymn now â€” as a photo, voice note, or file.")

# ----------------------------
# LEADER: /track
# ----------------------------
async def track_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in LEADER_IDS:
        return
    try:
        uid = int(context.args[0])
        with sqlite3.connect("bot_data.db") as conn:
            rows = conn.execute(
                "SELECT id, kind, msg FROM tickets WHERE uid=? ORDER BY id", (uid,)
            ).fetchall()

        txt = "\n".join(f"#{i} [{k}] {m}" for i, k, m in rows)
        await update.message.reply_text(f"ðŸ“œ History for {uid}:\n{txt}" if txt else "No history.")
    except Exception:
        await update.message.reply_text("Usage: /track <user_id>")

# ----------------------------
# MENU BUTTON
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
app.add_handler(CommandHandler("transfer", transfer_member))
app.add_handler(CommandHandler("broadcast", broadcast))
app.add_handler(CommandHandler("addsermon", addsermon))
app.add_handler(CommandHandler("adddevotional", adddevotional))
app.add_handler(CommandHandler("addhymn", addhymn))

app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_webapp_data))
app.add_handler(MessageHandler(filters.PHOTO | filters.VOICE | filters.Document.ALL, media_router))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, central_message_handler))

print("Church fellowship bot is running...")
app.run_polling()
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
