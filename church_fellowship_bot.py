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
# CONFIGURATION & ROLES
# ----------------------------
TOKEN = os.environ.get("BOT_TOKEN", "")

# Full Leaders: Receive incoming tickets and chat directly with members
raw_leaders = os.environ.get("LEADER_IDS", "6555910081,8399604250")
LEADER_IDS = [int(x.strip()) for x in raw_leaders.split(",") if x.strip().isdigit()]

# Support Admins: Manage workload, transfer tickets, broadcast, upload PDFs (No chatting / No history)
raw_support_admins = os.environ.get("SUPPORT_ADMIN_IDS", "999888777")
SUPPORT_ADMIN_IDS = [int(x.strip()) for x in raw_support_admins.split(",") if x.strip().isdigit()]

WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://church-app.yared6594.workers.dev")

# ----------------------------
# DATABASE MANAGEMENT
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
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            display_id TEXT,
            uid INTEGER,
            leader_id INTEGER,
            kind TEXT,
            msg TEXT,
            status TEXT DEFAULT 'open'
        )""")
        c.execute("""
        CREATE TABLE IF NOT EXISTS counters (
            name TEXT PRIMARY KEY,
            value INTEGER DEFAULT 0
        )""")
        c.execute("INSERT OR IGNORE INTO counters (name, value) VALUES ('bot', 0)")
        c.execute("INSERT OR IGNORE INTO counters (name, value) VALUES ('web', 0)")
        c.execute("""
        CREATE TABLE IF NOT EXISTS resources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id TEXT,
            file_type TEXT,
            name TEXT,
            cat TEXT
        )""")

def get_assigned_leader(uid):
    with sqlite3.connect("bot_data.db") as conn:
        r = conn.execute("SELECT assigned_leader FROM members WHERE user_id=?", (uid,)).fetchone()
    return r[0] if r and r[0] else None

def get_all_member_ids():
    with sqlite3.connect("bot_data.db") as conn:
        rows = conn.execute("SELECT user_id FROM members").fetchall()
    return [r[0] for r in rows]

def next_ticket_display(origin):
    with sqlite3.connect("bot_data.db") as conn:
        conn.execute("UPDATE counters SET value = value + 1 WHERE name=?", (origin,))
        val = conn.execute("SELECT value FROM counters WHERE name=?", (origin,)).fetchone()[0]
    return f"A{val}" if origin == "web" else str(val)

def get_ticket(display_id):
    with sqlite3.connect("bot_data.db") as conn:
        r = conn.execute(
            "SELECT id, uid, leader_id, status FROM tickets WHERE display_id=? COLLATE NOCASE",
            (display_id,)
        ).fetchone()
    return r

def get_active_ticket(uid):
    with sqlite3.connect("bot_data.db") as conn:
        r = conn.execute(
            "SELECT id, display_id, kind, msg FROM tickets WHERE uid=? AND status='open' ORDER BY id DESC LIMIT 1",
            (uid,)
        ).fetchone()
    return r

# ----------------------------
# MENUS
# ----------------------------
MAIN_MENU = ReplyKeyboardMarkup(
    [
        ["💬 Talk to a Fellowship Leader", "🙏 Prayer Request"],
        ["📖 Resources", "🔄 Request Reassignment"],
        [KeyboardButton("🖥️ Open Church App", web_app=WebAppInfo(url=WEBAPP_URL))],
    ],
    resize_keyboard=True
)

RESOURCE_MENU = ReplyKeyboardMarkup(
    [["🎙️ Sermons", "📅 Devotionals"], ["🎵 Hymns", "🔙 Back"]],
    resize_keyboard=True
)

# ----------------------------
# START COMMAND
# ----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if uid in SUPPORT_ADMIN_IDS:
        await update.message.reply_text(
            "====================================\n"
            "    SUPPORT ADMIN CONTROL PORTAL    \n"
            "====================================\n\n"
            "Available Management Commands:\n"
            "• /status - View leader workloads, active chats & talking users\n"
            "• /transfer <user_id> <leader_id> - Transfer member to another leader\n"
            "• /transfer_ticket <ticket_id> <leader_id> - Transfer specific ticket\n"
            "• /broadcast <message> - Send announcement to all members\n"
            "• /addpdf | /addsermon | /adddevotional | /addhymn - Upload materials\n\n"
            "⚠️ Notice: Support Admins cannot chat with members or view interaction history."
        )
        return

    if uid in LEADER_IDS:
        await update.message.reply_text(
            "====================================\n"
            "   FELLOWSHIP LEADER CONTROL PORTAL \n"
            "====================================\n\n"
            "Available Commands:\n"
            "• /ticket <id> - Reply to active ticket\n"
            "• /close <id> - Mark ticket resolved\n"
            "• /msg <user_id> <message> - Message member\n"
            "• /transfer <user_id> <leader_id> - Transfer member\n"
            "• /track <user_id> - View history\n"
            "• /broadcast <message> - Announcement"
        )
        return

    with sqlite3.connect("bot_data.db") as conn:
        conn.execute(
            "INSERT OR IGNORE INTO members (user_id, full_name) VALUES (?, ?)",
            (uid, update.effective_user.full_name)
        )

    await update.message.reply_text(
        "Welcome to the Church Fellowship Portal. 🙏",
        reply_markup=MAIN_MENU
    )

# ----------------------------
# STATUS & WORKLOAD DASHBOARD (SUPPORT ADMIN)
# ----------------------------
async def status_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in SUPPORT_ADMIN_IDS:
        return

    with sqlite3.connect("bot_data.db") as conn:
        # Leader Workload Summary
        workload = conn.execute("""
            SELECT leader_id, COUNT(*) 
            FROM tickets 
            WHERE status='open' 
            GROUP BY leader_id
        """).fetchall()
        
        # Active Conversations Detail
        active_chats = conn.execute("""
            SELECT display_id, uid, leader_id 
            FROM tickets 
            WHERE status='open'
        """).fetchall()

        total_members = conn.execute("SELECT COUNT(*) FROM members").fetchone()[0]

    workload_map = {lid: 0 for lid in LEADER_IDS}
    for lid, count in workload:
        if lid in workload_map:
            workload_map[lid] = count

    status_text = "📊 **SYSTEM WORKLOAD & LEADER STATUS**\n\n"
    status_text += f"👥 **Total Registered Members:** {total_members}\n"
    status_text += f"💬 **Users Currently Talking:** {len(active_chats)}\n\n"

    status_text += "⚖️ **Leader Ticket Load:**\n"
    for lid, count in workload_map.items():
        status_text += f"• Leader `{lid}`: **{count} active ticket(s)**\n"

    status_text += "\n📌 **Active Ticket Routing:**\n"
    if active_chats:
        for display_id, m_id, l_id in active_chats:
            status_text += f"• Ticket #{display_id} | Member `{m_id}` ➡️ Assigned Leader `{l_id}`\n"
    else:
        status_text += "• No open tickets at this time.\n"

    await update.message.reply_text(status_text)

# ----------------------------
# TRANSFERS (SUPPORT ADMIN & LEADERS)
# ----------------------------
async def transfer_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in SUPPORT_ADMIN_IDS and uid not in LEADER_IDS:
        return

    try:
        target_uid = int(context.args[0])
        new_leader = int(context.args[1])
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /transfer <user_id> <new_leader_id>")
        return

    if new_leader not in LEADER_IDS:
        await update.message.reply_text("Error: Target leader ID must belong to an active Full Leader.")
        return

    with sqlite3.connect("bot_data.db") as conn:
        conn.execute("UPDATE members SET assigned_leader=? WHERE user_id=?", (new_leader, target_uid))
        conn.execute("UPDATE tickets SET leader_id=? WHERE uid=? AND status='open'", (new_leader, target_uid))

    await update.message.reply_text(f"✅ Member {target_uid} successfully transferred to Leader {new_leader}.")

async def transfer_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in SUPPORT_ADMIN_IDS and uid not in LEADER_IDS:
        return

    try:
        ref = context.args[0].strip()
        new_leader = int(context.args[1])
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /transfer_ticket <ticket_id> <new_leader_id>")
        return

    if new_leader not in LEADER_IDS:
        await update.message.reply_text("Error: Target leader ID must belong to an active Full Leader.")
        return

    ticket = get_ticket(ref)
    if not ticket:
        await update.message.reply_text("Error: Ticket ID not found.")
        return

    internal_id, member_uid, _, status = ticket
    if status != 'open':
        await update.message.reply_text("Notice: Ticket is closed and cannot be transferred.")
        return

    with sqlite3.connect("bot_data.db") as conn:
        conn.execute("UPDATE tickets SET leader_id=? WHERE id=?", (new_leader, internal_id))
        conn.execute("UPDATE members SET assigned_leader=? WHERE user_id=?", (new_leader, member_uid))

    try:
        await context.bot.send_message(
            new_leader, 
            f"📌 Transferred Ticket #{ref}: Member `{member_uid}` has been assigned to you.\nReply via: /ticket {ref}"
        )
    except Exception:
        pass

    await update.message.reply_text(f"✅ Ticket #{ref} successfully reassigned to Leader {new_leader}.")

# ----------------------------
# CENTRAL MESSAGE ROUTERS
# ----------------------------
async def central_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if uid in SUPPORT_ADMIN_IDS:
        await update.message.reply_text("Access Denied: Support Admins cannot send direct messages to members.")
        return

    if uid in LEADER_IDS:
        if "reply_uid" in context.user_data:
            await leader_text_reply(update, context)
        else:
            await update.message.reply_text("Notice: Use `/ticket <id>` to activate a reply session.")
        return

    await member_logic(update, context)

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

    # Support Admin or Leader uploading resource materials
    if uid in SUPPORT_ADMIN_IDS or uid in LEADER_IDS:
        cat = context.user_data.pop("awaiting_resource_cat", None)
        if cat:
            with sqlite3.connect("bot_data.db") as conn:
                conn.execute(
                    "INSERT INTO resources (file_id, file_type, name, cat) VALUES (?,?,?,?)",
                    (file_id, file_type, caption or f"{cat[:-1].capitalize()}", cat)
                )
            await msg.reply_text(f"Resource / PDF successfully added to {cat.capitalize()}.")
            return

    if uid in SUPPORT_ADMIN_IDS:
        await msg.reply_text("Access Denied: Support Admins cannot send media directly to members.")
        return

    if uid in LEADER_IDS:
        if "reply_uid" in context.user_data:
            target_uid = context.user_data["reply_uid"]
            try:
                await send_media(context, target_uid, file_type, file_id, caption="✝️ Fellowship Leader Response")
                await msg.reply_text("Media delivered.")
            except Exception as e:
                await msg.reply_text(f"Delivery Failed: {e}")
            return
        await msg.reply_text("Notice: Use /ticket <id> prior to sending media.")
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
# MEMBER LOGIC
# ----------------------------
async def member_logic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text

    if text == "📖 Resources":
        await update.message.reply_text("Select a resource category:", reply_markup=RESOURCE_MENU)
        return

    if text in ["🎙️ Sermons", "📅 Devotionals", "🎵 Hymns", "🔙 Back"]:
        await send_resource_content(update, context)
        return

    if text == "🙏 Prayer Request":
        context.user_data["awaiting_prayer"] = True
        await update.message.reply_text("Enter your prayer request:")
        return

    if context.user_data.get("awaiting_prayer"):
        context.user_data.pop("awaiting_prayer")
        await route_to_leader(update, context, text, kind="prayer_request")
        return

    if text == "💬 Talk to a Fellowship Leader":
        await update.message.reply_text("Type your message below and a leader will assist you.")
        return

    await route_to_leader(update, context, text, kind="message")

async def route_to_leader(update, context, text, kind, file_id=None, file_type=None, origin="bot"):
    uid = update.effective_user.id

    leader_id = get_assigned_leader(uid)
    if not leader_id or leader_id not in LEADER_IDS:
        leader_id = LEADER_IDS[0] if LEADER_IDS else None
        if leader_id:
            with sqlite3.connect("bot_data.db") as conn:
                conn.execute("UPDATE members SET assigned_leader=? WHERE user_id=?", (leader_id, uid))

    active_ticket = get_active_ticket(uid)

    if active_ticket:
        _, display_id, _, _ = active_ticket
        msg_body = f"💬 Follow-up Ticket #{display_id}\nMember ID: {uid}\nContent: {text}\n\nReply: /ticket {display_id}"
        
        # Route strictly to FULL LEADERS ONLY (Support Admins excluded)
        for lid in LEADER_IDS:
            try:
                if file_id:
                    await send_media(context, lid, file_type, file_id, caption=msg_body)
                else:
                    await context.bot.send_message(lid, msg_body)
            except Exception:
                pass
        await update.message.reply_text("✅ Follow-up sent to leaders.")
        return

    display_id = next_ticket_display(origin)
    with sqlite3.connect("bot_data.db") as conn:
        conn.execute(
            "INSERT INTO tickets (display_id, uid, leader_id, kind, msg, status) VALUES (?,?,?,?,?,'open')",
            (display_id, uid, leader_id, kind, text)
        )

    msg_body = f"📥 Ticket #{display_id} [{kind}]\nMember ID: {uid}\nContent: {text}\n\nReply: /ticket {display_id}"
    
    # Route strictly to FULL LEADERS ONLY
    for lid in LEADER_IDS:
        try:
            if file_id:
                await send_media(context, lid, file_type, file_id, caption=msg_body)
            else:
                await context.bot.send_message(lid, msg_body)
        except Exception:
            pass

    await update.message.reply_text(f"✅ Ticket #{display_id} created. A leader will reply shortly.")

# ----------------------------
# RESOURCE DISTRIBUTION & UPLOADS
# ----------------------------
async def send_resource_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    uid = update.effective_user.id
    cat_map = {"🎙️ Sermons": "sermons", "📅 Devotionals": "devotionals", "🎵 Hymns": "hymns"}

    if text == "🔙 Back":
        await update.message.reply_text("Returning to main menu.", reply_markup=MAIN_MENU)
        return

    if text not in cat_map:
        return

    with sqlite3.connect("bot_data.db") as conn:
        rows = conn.execute("SELECT file_id, file_type, name FROM resources WHERE cat=?", (cat_map[text],)).fetchall()

    if not rows:
        await update.message.reply_text("No materials currently available.")
        return

    for file_id, file_type, name in rows:
        try:
            await send_media(context, uid, file_type, file_id, caption=name)
        except Exception:
            pass

async def add_resource(update: Update, context: ContextTypes.DEFAULT_TYPE, category: str):
    uid = update.effective_user.id
    if uid not in SUPPORT_ADMIN_IDS and uid not in LEADER_IDS:
        return
    context.user_data["awaiting_resource_cat"] = category
    await update.message.reply_text(f"Upload media or PDF for the {category.capitalize()} category now.")

# ----------------------------
# LEADER / ADMIN COMMANDS
# ----------------------------
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in SUPPORT_ADMIN_IDS and uid not in LEADER_IDS:
        return

    text = " ".join(context.args)
    if not text:
        await update.message.reply_text("Usage: /broadcast <message>")
        return

    member_ids = get_all_member_ids()
    sent, failed = 0, 0
    for mid in member_ids:
        try:
            await context.bot.send_message(mid, f"📢 Church Announcement:\n{text}")
            sent += 1
        except Exception:
            failed += 1

    await update.message.reply_text(f"Broadcast sent. Success: {sent}, Failed: {failed}.")

async def track_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid in SUPPORT_ADMIN_IDS:
        await update.message.reply_text("Access Denied: Support Admins cannot view member interaction history.")
        return
    if uid not in LEADER_IDS:
        return

    try:
        m_id = int(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /track <user_id>")
        return

    with sqlite3.connect("bot_data.db") as conn:
        rows = conn.execute("SELECT display_id, kind, msg, status FROM tickets WHERE uid=?", (m_id,)).fetchall()

    txt = "\n".join(f"#{i} [{s.upper()}] {m}" for i, k, m, s in rows)
    await update.message.reply_text(f"📜 History for Member {m_id}:\n{txt}" if txt else "No records found.")

async def reply_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid in SUPPORT_ADMIN_IDS:
        await update.message.reply_text("Access Denied: Support Admins cannot reply to tickets.")
        return
    if uid not in LEADER_IDS:
        return

    try:
        ref = context.args[0].strip()
    except IndexError:
        await update.message.reply_text("Usage: /ticket <ticket_id>")
        return

    ticket = get_ticket(ref)
    if not ticket:
        await update.message.reply_text("Error: Ticket ID not found.")
        return

    _, target_uid, _, status = ticket
    if status != 'open':
        await update.message.reply_text("Ticket is closed.")
        return

    context.user_data["reply_uid"] = target_uid
    await update.message.reply_text(f"Active Session: Replying to Ticket #{ref} (Member ID: {target_uid}).")

async def close_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid in SUPPORT_ADMIN_IDS:
        await update.message.reply_text("Access Denied: Support Admins cannot resolve tickets.")
        return
    if uid not in LEADER_IDS:
        return

    try:
        ref = context.args[0].strip()
    except IndexError:
        await update.message.reply_text("Usage: /close <ticket_id>")
        return

    ticket = get_ticket(ref)
    if not ticket:
        await update.message.reply_text("Error: Ticket ID not found.")
        return

    internal_id, _, _, status = ticket
    if status == 'closed':
        await update.message.reply_text("Ticket is already closed.")
        return

    with sqlite3.connect("bot_data.db") as conn:
        conn.execute("UPDATE tickets SET status='closed' WHERE id=?", (internal_id,))

    context.user_data.pop("reply_uid", None)
    await update.message.reply_text(f"✅ Ticket #{ref} resolved.")

async def leader_text_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target_uid = context.user_data.get("reply_uid")
    text = update.message.text
    try:
        await context.bot.send_message(target_uid, f"✝️ Fellowship Leader:\n{text}")
        await update.message.reply_text("Reply delivered.")
    except Exception as e:
        await update.message.reply_text(f"Delivery Failed: {e}")

# ----------------------------
# INIT & STARTUP
# ----------------------------
async def post_init(application):
    await application.bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(text="Church App", web_app=WebAppInfo(url=WEBAPP_URL))
    )

init_db()

app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("status", status_dashboard))
app.add_handler(CommandHandler("transfer", transfer_member))
app.add_handler(CommandHandler("transfer_ticket", transfer_ticket))
app.add_handler(CommandHandler("broadcast", broadcast))

app.add_handler(CommandHandler("addpdf", lambda u, c: add_resource(u, c, "devotionals")))
app.add_handler(CommandHandler("addsermon", lambda u, c: add_resource(u, c, "sermons")))
app.add_handler(CommandHandler("adddevotional", lambda u, c: add_resource(u, c, "devotionals")))
app.add_handler(CommandHandler("addhymn", lambda u, c: add_resource(u, c, "hymns")))

app.add_handler(CommandHandler("ticket", reply_ticket))
app.add_handler(CommandHandler("close", close_ticket))
app.add_handler(CommandHandler("track", track_member))

app.add_handler(MessageHandler(filters.PHOTO | filters.VOICE | filters.Document.ALL, media_router))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, central_message_handler))

print("Church Fellowship Portal with Support Admin active...")
app.run_polling()
