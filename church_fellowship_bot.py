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
TOKEN = os.environ["BOT_TOKEN"]
LEADER_IDS = [6555910081, 8399604250]  # Pastor/Elder Telegram User IDs

# Support Leaders (Admins who manage workloads, transfer tickets, broadcast, and upload resources, but cannot chat or view history)
raw_support_admins = os.environ.get("SUPPORT_ADMIN_IDS", "999888777")
SUPPORT_ADMIN_IDS = [int(x.strip()) for x in raw_support_admins.split(",") if x.strip().isdigit()]

WEBAPP_URL = "https://church-app.yared6594.workers.dev"

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
        CREATE TABLE IF NOT EXISTS leader_status (
            leader_id INTEGER PRIMARY KEY,
            is_online INTEGER DEFAULT 1
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

        for lid in LEADER_IDS:
            c.execute(
                "INSERT OR IGNORE INTO leader_status (leader_id, is_online) VALUES (?, 1)",
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

def next_ticket_display(origin):
    """
    Two independent counters: 'bot' -> plain numbers (1, 2, 3...),
    'web' (Mini App) -> A-prefixed numbers (A1, A2, A3...).
    """
    with sqlite3.connect("bot_data.db") as conn:
        conn.execute("UPDATE counters SET value = value + 1 WHERE name=?", (origin,))
        val = conn.execute("SELECT value FROM counters WHERE name=?", (origin,)).fetchone()[0]
    return f"A{val}" if origin == "web" else str(val)

def get_ticket(display_id):
    """Look up a ticket by its human-facing number, e.g. '7' or 'A3'."""
    with sqlite3.connect("bot_data.db") as conn:
        r = conn.execute(
            "SELECT id, uid, leader_id, status FROM tickets WHERE display_id=? COLLATE NOCASE",
            (display_id,)
        ).fetchone()
    return r  # (internal_id, uid, leader_id, status) or None

def get_active_ticket(uid):
    with sqlite3.connect("bot_data.db") as conn:
        r = conn.execute(
            "SELECT id, display_id, kind, msg FROM tickets WHERE uid=? AND status='open' ORDER BY id DESC LIMIT 1",
            (uid,)
        ).fetchone()
    return r  # (internal_id, display_id, kind, msg) or None

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
            "🛡️ **SUPPORT LEADER CONTROL PORTAL**\n"
            "──────────────────────────────\n\n"
            "📋 **Operations & Management Commands:**\n"
            "• `/status` — View real-time leader workloads & active ticket routing\n"
            "• `/transfer_ticket <ticket_id> <leader_id>` — Transfer an open ticket to another leader\n"
            "• `/admintransfer <user_id> <leader_id>` — Reassign a member to a new leader\n"
            "• `/adminbroadcast <message>` — Send an announcement to all members\n\n"
            "📚 **Resource Management Commands:**\n"
            "• `/adminaddpdf` | `/adminaddsermon` | `/adminadddevotional` | `/adminaddhymn` — Upload church resources\n\n"
            "───────────── Notice ─────────────\n"
            "⚠️ **Privacy Restrictions:** Support Leaders manage operations only and do not have access to view conversation histories or directly chat with members.",
            parse_mode="Markdown"
        )
        return

    if uid in LEADER_IDS:
        await update.message.reply_text(
            "====================================\n"
            "   FELLOWSHIP LEADER CONTROL PORTAL   \n"
            "====================================\n\n"
            "Available Administrative Commands:\n"
            "• /ticket <id> - Reply to an active ticket\n"
            "• /close <id> - Resolve and close an active ticket\n"
            "• /msg <user_id> <message> - Send direct message to assigned member\n"
            "• /transfer <user_id> <new_leader_id> - Transfer member to another leader\n"
            "• /track <user_id> - View interaction history for assigned member\n"
            "• /broadcast <message> - Send announcement to all members\n"
            "• /addsermon | /adddevotional | /addhymn - Add resource media"
        )
        return

    with sqlite3.connect("bot_data.db") as conn:
        conn.execute(
            "INSERT OR IGNORE INTO members (user_id, full_name) VALUES (?, ?)",
            (uid, update.effective_user.full_name)
        )

    await update.message.reply_text(
        "Welcome to the Church Fellowship Portal. 🙏\n"
        "You may communicate with your assigned fellowship leader, submit prayer requests, or access church resources below.",
        reply_markup=MAIN_MENU
    )

# ----------------------------
# CENTRAL MESSAGE ROUTERS
# ----------------------------
async def central_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if uid in SUPPORT_ADMIN_IDS:
        await update.message.reply_text("❌ Access Denied: Support Leaders are not permitted to chat directly with members.")
        return

    if uid in LEADER_IDS:
        if "reply_uid" in context.user_data:
            await leader_text_reply(update, context)
        else:
            await update.message.reply_text("Administrative Notice: Please use /ticket <id> to respond to an inquiry.")
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

    if uid in SUPPORT_ADMIN_IDS or uid in LEADER_IDS:
        cat = context.user_data.pop("awaiting_resource_cat", None)
        if cat:
            with sqlite3.connect("bot_data.db") as conn:
                conn.execute(
                    "INSERT INTO resources (file_id, file_type, name, cat) VALUES (?,?,?,?)",
                    (file_id, file_type, caption or f"{cat[:-1].capitalize()}", cat)
                )
            await msg.reply_text(f"Resource successfully added to {cat.capitalize()}.")
            return

    if uid in SUPPORT_ADMIN_IDS:
        await msg.reply_text("❌ Access Denied: Support Leaders cannot send direct attachments to members.")
        return

    if uid in LEADER_IDS:
        if "reply_uid" in context.user_data:
            target_uid = context.user_data.pop("reply_uid")
            if get_assigned_leader(target_uid) != uid:
                await msg.reply_text("Access Denied: You are no longer assigned to this member.")
                return
            try:
                await send_media(context, target_uid, file_type, file_id, caption="✝️ Fellowship Leader Response")
                await msg.reply_text("Message successfully delivered.")
            except Exception:
                await msg.reply_text("Delivery Failed: The member may have blocked communications.")
            return

        await msg.reply_text("Administrative Notice: Use /ticket <id> prior to sending media attachments.")
        return

    await route_to_leader(update, context, caption or f"[{file_type}]", kind=file_type, file_id=file_id, file_type=file_type)

async def send_media(context, chat_id, file_type, file_id, caption=None):
    if file_type == "photo":
        await context.bot.send_photo(chat_id, file_id, caption=caption)
    elif file_type == "voice":
        await context.bot.send_voice(chat_id, file_id, caption=caption)
    else:
        await context.bot.send_document(chat_id, file_id, caption=caption)

async def handle_webapp_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        data = json.loads(update.effective_message.web_app_data.data)
        text = data.get("text", "").strip()
        kind = data.get("type", "message")
    except (json.JSONDecodeError, AttributeError):
        await update.message.reply_text("Error processing submission. Please try again.")
        return

    if not text:
        await update.message.reply_text("Submission empty. Nothing was sent.")
        return

    await route_to_leader(update, context, text, kind=kind, origin="web")

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
        await update.message.reply_text("Please enter your prayer request. It will be sent confidentially to your leader.")
        return

    if context.user_data.get("awaiting_prayer"):
        context.user_data.pop("awaiting_prayer")
        await route_to_leader(update, context, text, kind="prayer_request")
        return

    if text == "🔄 Request Reassignment":
        old_leader = get_assigned_leader(uid)
        available = [l for l in LEADER_IDS if l != old_leader]
        new_leader = random.choice(available) if available else random.choice(LEADER_IDS)

        with sqlite3.connect("bot_data.db") as conn:
            conn.execute("UPDATE members SET assigned_leader=? WHERE user_id=?", (new_leader, uid))
            conn.execute("UPDATE tickets SET leader_id=? WHERE uid=? AND status='open'", (new_leader, uid))

        if old_leader:
            try:
                await context.bot.send_message(
                    old_leader,
                    f"Notice: Member ID {uid} has requested reassignment. Access to this member has been revoked."
                )
            except Exception:
                pass

        active_t = get_active_ticket(uid)
        try:
            if active_t:
                _, t_display_id, t_kind, t_msg = active_t
                await context.bot.send_message(
                    new_leader,
                    f"📌 Reassignment Notification: Member ID {uid} assigned to you.\n"
                    f"Pending Ticket #{t_display_id} [{t_kind}]:\n\"{t_msg}\"\n\n"
                    f"Reply via: /ticket {t_display_id}"
                )
            else:
                await context.bot.send_message(
                    new_leader,
                    f"📌 Reassignment Notification: Member ID {uid} assigned to you.\nNo open tickets pending."
                )
        except Exception:
            pass

        await update.message.reply_text("You have been assigned to a new fellowship leader.")
        return

    if text == "💬 Talk to a Fellowship Leader":
        await update.message.reply_text("Go ahead, type your message and I'll pass it along.")
        return

    await route_to_leader(update, context, text, kind="message")

async def route_to_leader(update, context, text, kind, file_id=None, file_type=None, origin="bot"):
    uid = update.effective_user.id

    leader_id = get_assigned_leader(uid)
    if not leader_id:
        leader_id = random.choice(LEADER_IDS)
        with sqlite3.connect("bot_data.db") as conn:
            conn.execute("UPDATE members SET assigned_leader=? WHERE user_id=?", (leader_id, uid))

    active_ticket = get_active_ticket(uid)

    if active_ticket:
        _, display_id, _, _ = active_ticket
        try:
            msg_body = f"💬 Follow-up on Ticket #{display_id}\nMember ID: {uid}\nContent: {text}\n\nReply via: /ticket {display_id}"
            if file_id:
                await send_media(context, leader_id, file_type, file_id, caption=msg_body)
            else:
                await context.bot.send_message(leader_id, msg_body)
            await update.message.reply_text("✅ Message sent to your leader.")
        except Exception:
            await update.message.reply_text("Delivery failed. Please try again.")
        return

    display_id = next_ticket_display(origin)
    with sqlite3.connect("bot_data.db") as conn:
        conn.execute(
            "INSERT INTO tickets (display_id, uid, leader_id, kind, msg, status) VALUES (?,?,?,?,?,'open')",
            (display_id, uid, leader_id, kind, text)
        )

    labels = {
        "prayer_request": "🙏 Prayer Request",
        "photo": "🖼️ Photo Submission",
        "voice": "🎤 Voice Note",
        "document": "📎 Document",
        "bible_study": "📖 Bible Study Plan",
    }
    label = labels.get(kind, "📥 Inquiry")

    try:
        msg_body = f"{label} #{display_id}\nMember ID: {uid}\nContent: {text}\n\nTo respond: /ticket {display_id}"
        if file_id:
            await send_media(context, leader_id, file_type, file_id, caption=msg_body)
        else:
            await context.bot.send_message(leader_id, msg_body)
        await update.message.reply_text(f"✅ Message delivered (Ticket #{display_id}).")
    except Exception:
        await update.message.reply_text(f"Ticket #{display_id} logged. Leader notification pending.")

# ----------------------------
# RESOURCE DISTRIBUTION
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
        rows = conn.execute(
            "SELECT file_id, file_type, name FROM resources WHERE cat=?",
            (cat_map[text],)
        ).fetchall()

    if not rows:
        await update.message.reply_text("No materials currently available in this category.")
        return

    for file_id, file_type, name in rows:
        try:
            await send_media(context, uid, file_type, file_id, caption=name)
        except Exception:
            pass

# ----------------------------
# LEADER COMMAND HANDLERS
# ----------------------------
async def reply_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    leader_id = update.effective_user.id
    if is_support_leader_blocked(leader_id):
        await block_support_chat_attempts(update)
        return
    if leader_id not in LEADER_IDS:
        return

    try:
        ref = context.args[0].strip()
    except IndexError:
        await update.message.reply_text("Usage: /ticket <ticket_id>  (e.g. /ticket 7 or /ticket A3)")
        return

    ticket = get_ticket(ref)
    if not ticket:
        await update.message.reply_text("Error: Ticket ID not found.")
        return

    _, target_uid, _, status = ticket

    if status != 'open':
        await update.message.reply_text("Notice: This ticket has already been resolved and closed.")
        return

    if get_assigned_leader(target_uid) != leader_id:
        await update.message.reply_text("Access Denied: You are not authorized to communicate with this member.")
        return

    context.user_data["reply_uid"] = target_uid
    await update.message.reply_text(f"Active Session: Replying to Ticket #{ref} (Member ID: {target_uid}). Enter message:")

async def close_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    leader_id = update.effective_user.id
    if is_support_leader_blocked(leader_id):
        await block_support_chat_attempts(update)
        return
    if leader_id not in LEADER_IDS:
        return

    try:
        ref = context.args[0].strip()
    except IndexError:
        await update.message.reply_text("Usage: /close <ticket_id>  (e.g. /close 7 or /close A3)")
        return

    ticket = get_ticket(ref)
    if not ticket:
        await update.message.reply_text("Error: Ticket ID not found.")
        return

    internal_id, target_uid, _, status = ticket

    if get_assigned_leader(target_uid) != leader_id:
        await update.message.reply_text("Access Denied: You are not authorized to manage this ticket.")
        return

    if status == 'closed':
        await update.message.reply_text("Notice: Ticket is already marked closed.")
        return

    with sqlite3.connect("bot_data.db") as conn:
        conn.execute("UPDATE tickets SET status='closed' WHERE id=?", (internal_id,))

    await update.message.reply_text(f"✅ Ticket #{ref} has been marked as resolved.")
    try:
        await context.bot.send_message(
            target_uid,
            f"Notice: Your support request (Ticket #{ref}) has been marked as resolved by your fellowship leader."
        )
    except Exception:
        pass

async def msg_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    leader_id = update.effective_user.id
    if is_support_leader_blocked(leader_id):
        await block_support_chat_attempts(update)
        return
    if leader_id not in LEADER_IDS:
        return

    if len(context.args) < 2:
        await update.message.reply_text("Usage: /msg <user_id> <message>")
        return

    try:
        target_uid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Error: Invalid User ID format.")
        return

    if get_assigned_leader(target_uid) != leader_id:
        await update.message.reply_text("Access Denied: You are not the assigned leader for this member.")
        return

    text = " ".join(context.args[1:])
    try:
        await context.bot.send_message(target_uid, f"✝️ Fellowship Leader:\n{text}")
        await update.message.reply_text("Message successfully delivered.")
    except Exception:
        await update.message.reply_text("Delivery Failed: Unable to reach member.")

async def leader_text_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    acting_leader = update.effective_user.id
    uid = context.user_data.pop("reply_uid")

    if get_assigned_leader(uid) != acting_leader:
        await update.message.reply_text("Access Denied: Reassignment occurred prior to reply.")
        return

    text = update.message.text
    try:
        await context.bot.send_message(uid, f"✝️ Fellowship Leader:\n{text}")
        await update.message.reply_text("Reply successfully delivered.")
    except Exception:
        await update.message.reply_text("Delivery Failed: Member unreachable.")

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
        await update.message.reply_text("Error: Target leader ID not recognized.")
        return

    old_leader = get_assigned_leader(target_uid)

    with sqlite3.connect("bot_data.db") as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE members SET assigned_leader=? WHERE user_id=?", (new_leader, target_uid))
        if cursor.rowcount == 0:
            await update.message.reply_text(
                f"❌ Error: User ID `{target_uid}` not found in registered members."
            )
            return
        cursor.execute("UPDATE tickets SET leader_id=? WHERE uid=? AND status='open'", (new_leader, target_uid))

    try:
        await context.bot.send_message(
            target_uid, "Notice: You have been transferred to a new fellowship leader."
        )
    except Exception:
        pass

    if old_leader and old_leader != new_leader:
        try:
            await context.bot.send_message(
                old_leader,
                f"Notice: Member ID {target_uid} transferred. Access permissions revoked."
            )
        except Exception:
            pass

    active_t = get_active_ticket(target_uid)
    try:
        if active_t:
            _, t_display_id, t_kind, t_msg = active_t
            await context.bot.send_message(
                new_leader,
                f"📌 Transfer Received: Member ID {target_uid} assigned to you.\n"
                f"Active Ticket #{t_display_id} [{t_kind}]:\n\"{t_msg}\"\n\n"
                f"Reply via: /ticket {t_display_id}"
            )
        else:
            await context.bot.send_message(
                new_leader,
                f"📌 Transfer Received: Member ID {target_uid} assigned to you.\nNo active open tickets."
            )
    except Exception:
        pass

    await update.message.reply_text(f"✅ Member {target_uid} successfully transferred to Leader {new_leader}.")

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
            await context.bot.send_message(mid, f"📢 Church Announcement:\n{text}")
            sent += 1
        except Exception:
            failed += 1

    await update.message.reply_text(f"Broadcast complete. Delivered: {sent}, Failed: {failed}.")

async def track_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    leader_id = update.effective_user.id
    if is_support_leader_blocked(leader_id):
        await block_support_chat_attempts(update)
        return
    if leader_id not in LEADER_IDS:
        return

    try:
        uid = int(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /track <user_id>")
        return

    if get_assigned_leader(uid) != leader_id:
        await update.message.reply_text("Access Denied: You can only view history for members currently assigned to you.")
        return

    with sqlite3.connect("bot_data.db") as conn:
        rows = conn.execute(
            "SELECT display_id, kind, msg, status FROM tickets WHERE uid=? ORDER BY id", (uid,)
        ).fetchall()

    txt = "\n".join(f"#{i} [{s.upper()}] [{k}] {m}" for i, k, m, s in rows)
    await update.message.reply_text(f"📜 Interaction History for Member {uid}:\n{txt}" if txt else "No records found.")

async def addsermon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in LEADER_IDS:
        return
    context.user_data["awaiting_resource_cat"] = "sermons"
    await update.message.reply_text("Upload media for Sermons category (Photo, Voice, or File).")

async def adddevotional(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in LEADER_IDS:
        return
    context.user_data["awaiting_resource_cat"] = "devotionals"
    await update.message.reply_text("Upload media for Devotionals category (Photo, Voice, or File).")

async def addhymn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in LEADER_IDS:
        return
    context.user_data["awaiting_resource_cat"] = "hymns"
    await update.message.reply_text("Upload media for Hymns category (Photo, Voice, or File).")

# ----------------------------
# SUPPORT LEADER ADDITIONS
# ----------------------------
async def status_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Support Leader command: /status — view leader workloads and active tickets."""
    uid = update.effective_user.id
    if uid not in SUPPORT_ADMIN_IDS:
        return

    with sqlite3.connect("bot_data.db") as conn:
        workload = conn.execute(
            "SELECT leader_id, COUNT(*) FROM tickets WHERE status='open' GROUP BY leader_id"
        ).fetchall()
        active_chats = conn.execute(
            "SELECT display_id, uid, leader_id FROM tickets WHERE status='open'"
        ).fetchall()
        total_members = conn.execute("SELECT COUNT(*) FROM members").fetchone()[0]

    workload_map = {lid: 0 for lid in LEADER_IDS}
    for lid, count in workload:
        if lid in workload_map:
            workload_map[lid] = count

    status_text = "🌐 **SYSTEM DASHBOARD & WORKLOAD OVERVIEW**\n"
    status_text += "──────────────────────────────\n\n"
    status_text += "📊 **System Metrics:**\n"
    status_text += f"• Total Registered Members: **{total_members}**\n"
    status_text += f"• Active Conversations: **{len(active_chats)}**\n\n"

    status_text += "⚖️ **Leader Workload Distribution:**\n"
    for lid, count in workload_map.items():
        status_text += f"• Leader `{lid}`: **{count}** open ticket(s)\n"

    status_text += "\n🔀 **Active Ticket Routing:**\n"
    if active_chats:
        for display_id, m_id, l_id in active_chats:
            status_text += f"• Ticket **#{display_id}** | Member `{m_id}` ➔ Leader `{l_id}`\n"
    else:
        status_text += "• No open tickets at this time.\n"

    await update.message.reply_text(status_text, parse_mode="Markdown")

async def transfer_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Support Leader command: /transfer_ticket <ticket_id> <new_leader_id>"""
    uid = update.effective_user.id
    if uid not in SUPPORT_ADMIN_IDS:
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

    # Notify New Leader
    try:
        await context.bot.send_message(
            new_leader,
            f"📌 Transferred Ticket #{ref}: Member `{member_uid}` assigned to you.\nReply via: /ticket {ref}"
        )
    except Exception:
        pass

    # Notify Target Member
    try:
        await context.bot.send_message(
            member_uid,
            f"Notice: Your open ticket (#{ref}) has been transferred to a new fellowship leader."
        )
    except Exception:
        pass

    await update.message.reply_text(f"✅ Ticket #{ref} successfully reassigned to Leader {new_leader}.")

async def admin_transfer_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Support Leader command: /admintransfer <user_id> <new_leader_id>"""
    uid = update.effective_user.id
    if uid not in SUPPORT_ADMIN_IDS:
        return

    try:
        target_uid = int(context.args[0])
        new_leader = int(context.args[1])
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /admintransfer <user_id> <new_leader_id>")
        return

    if new_leader not in LEADER_IDS:
        await update.message.reply_text("Error: Target leader ID must belong to an active Full Leader.")
        return

    with sqlite3.connect("bot_data.db") as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE members SET assigned_leader=? WHERE user_id=?", (new_leader, target_uid))
        if cursor.rowcount == 0:
            await update.message.reply_text(
                f"❌ Error: User ID `{target_uid}` not found in registered members.\n"
                f"💡 Tip: If `{target_uid}` is a Ticket ID, use: `/transfer_ticket {target_uid} {new_leader}`"
            )
            return
        cursor.execute("UPDATE tickets SET leader_id=? WHERE uid=? AND status='open'", (new_leader, target_uid))

    # Notify Target Member
    try:
        await context.bot.send_message(
            target_uid,
            "Notice: You have been assigned to a new fellowship leader."
        )
    except Exception:
        pass

    # Notify New Leader
    active_t = get_active_ticket(target_uid)
    try:
        if active_t:
            _, t_display_id, t_kind, t_msg = active_t
            await context.bot.send_message(
                new_leader,
                f"📌 Transfer Received: Member ID `{target_uid}` assigned to you.\n"
                f"Active Ticket #{t_display_id} [{t_kind}]:\n\"{t_msg}\"\n\n"
                f"Reply via: /ticket {t_display_id}"
            )
        else:
            await context.bot.send_message(
                new_leader,
                f"📌 Transfer Received: Member ID `{target_uid}` assigned to you.\nNo active open tickets."
            )
    except Exception:
        pass

    await update.message.reply_text(f"✅ Member {target_uid} successfully transferred to Leader {new_leader}.")

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Support Leader command: /adminbroadcast <message>"""
    uid = update.effective_user.id
    if uid not in SUPPORT_ADMIN_IDS:
        return

    text = " ".join(context.args)
    if not text:
        await update.message.reply_text("Usage: /adminbroadcast <message>")
        return

    with sqlite3.connect("bot_data.db") as conn:
        member_ids = [r[0] for r in conn.execute("SELECT user_id FROM members").fetchall()]

    sent, failed = 0, 0
    for mid in member_ids:
        try:
            await context.bot.send_message(mid, f"📢 Church Announcement:\n{text}")
            sent += 1
        except Exception:
            failed += 1

    await update.message.reply_text(f"Broadcast completed. Success: {sent}, Failed: {failed}.")

async def admin_add_resource(update: Update, context: ContextTypes.DEFAULT_TYPE, category: str):
    """Support Leader upload trigger for media resources & PDFs"""
    uid = update.effective_user.id
    if uid not in SUPPORT_ADMIN_IDS:
        return

    context.user_data["awaiting_resource_cat"] = category
    await update.message.reply_text(f"Upload media or PDF for the {category.capitalize()} category now.")

def is_support_leader_blocked(uid: int) -> bool:
    """Returns True if user is a Support Leader trying to perform direct chat/history actions."""
    return uid in SUPPORT_ADMIN_IDS

async def block_support_chat_attempts(update: Update):
    """Blocks Support Leaders from attempting direct chat or viewing history."""
    if is_support_leader_blocked(update.effective_user.id):
        await update.message.reply_text("❌ Access Denied: Support Leaders cannot view history or chat directly with members.")
        return True
    return False

# ----------------------------
# INITIALIZATION & EXECUTION
# ----------------------------
async def post_init(application):
    await application.bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(text="Church App", web_app=WebAppInfo(url=WEBAPP_URL))
    )

init_db()

app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("ticket", reply_ticket))
app.add_handler(CommandHandler("close", close_ticket))
app.add_handler(CommandHandler("msg", msg_member))
app.add_handler(CommandHandler("track", track_member))
app.add_handler(CommandHandler("transfer", transfer_member))
app.add_handler(CommandHandler("broadcast", broadcast))
app.add_handler(CommandHandler("addsermon", addsermon))
app.add_handler(CommandHandler("adddevotional", adddevotional))
app.add_handler(CommandHandler("addhymn", addhymn))

# Support Leader Command Handlers
app.add_handler(CommandHandler("status", status_dashboard))
app.add_handler(CommandHandler("transfer_ticket", transfer_ticket))
app.add_handler(CommandHandler("admintransfer", admin_transfer_member))
app.add_handler(CommandHandler("adminbroadcast", admin_broadcast))
app.add_handler(CommandHandler("adminaddpdf", lambda u, c: admin_add_resource(u, c, "devotionals")))
app.add_handler(CommandHandler("adminaddsermon", lambda u, c: admin_add_resource(u, c, "sermons")))
app.add_handler(CommandHandler("adminadddevotional", lambda u, c: admin_add_resource(u, c, "devotionals")))
app.add_handler(CommandHandler("adminaddhymn", lambda u, c: admin_add_resource(u, c, "hymns")))

app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_webapp_data))
app.add_handler(MessageHandler(filters.PHOTO | filters.VOICE | filters.Document.ALL, media_router))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, central_message_handler))

print("Church Fellowship Portal operating normally...")
app.run_polling()
