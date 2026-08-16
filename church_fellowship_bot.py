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
# CONFIGURATION
# ----------------------------
TOKEN = os.environ["BOT_TOKEN"]
LEADER_IDS = [6555910081, 8399604250]  # Pastor/Elder Telegram User IDs

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

def get_ticket(ticket_id):
    with sqlite3.connect("bot_data.db") as conn:
        r = conn.execute(
            "SELECT uid, leader_id, status FROM tickets WHERE id=?",
            (ticket_id,)
        ).fetchone()
    return r

def get_active_ticket(uid):
    with sqlite3.connect("bot_data.db") as conn:
        r = conn.execute(
            "SELECT id, kind, msg FROM tickets WHERE uid=? AND status='open' ORDER BY id DESC LIMIT 1",
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

    if uid in LEADER_IDS:
        cat = context.user_data.pop("awaiting_resource_cat", None)
        if cat:
            with sqlite3.connect("bot_data.db") as conn:
                conn.execute(
                    "INSERT INTO resources (file_id, file_type, name, cat) VALUES (?,?,?,?)",
                    (file_id, file_type, caption or f"{cat[:-1].capitalize()}", cat)
                )
            await msg.reply_text(f"Resource successfully added to {cat.capitalize()}.")
            return

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

    await route_to_leader(update, context, text, kind=kind)

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
                t_id, t_kind, t_msg = active_t
                await context.bot.send_message(
                    new_leader,
                    f"📌 Reassignment Notification: Member ID {uid} assigned to you.\n"
                    f"Pending Ticket #{t_id} [{t_kind}]:\n\"{t_msg}\"\n\n"
                    f"Reply via: /ticket {t_id}"
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
        await update.message.reply_text("Type your message below and press send.")
        return

    await route_to_leader(update, context, text, kind="message")

async def route_to_leader(update, context, text, kind, file_id=None, file_type=None):
    uid = update.effective_user.id

    # Enforce Single Open Ticket Rule
    active_ticket = get_active_ticket(uid)
    if active_ticket:
        await update.message.reply_text(
            f"Notice: You currently have an active support ticket (#{active_ticket[0]}).\n"
            "Please wait for your fellowship leader to respond and close your current request before submitting a new one."
        )
        return

    leader_id = get_assigned_leader(uid)
    if not leader_id:
        leader_id = random.choice(LEADER_IDS)
        with sqlite3.connect("bot_data.db") as conn:
            conn.execute("UPDATE members SET assigned_leader=? WHERE user_id=?", (leader_id, uid))

    with sqlite3.connect("bot_data.db") as conn:
        cur = conn.execute(
            "INSERT INTO tickets (uid, leader_id, kind, msg, status) VALUES (?,?,?,?,'open')",
            (uid, leader_id, kind, text)
        )
        ticket_id = cur.lastrowid

    labels = {
        "prayer_request": "🙏 Prayer Request",
        "photo": "🖼️ Photo Submission",
        "voice": "🎤 Voice Note",
        "document": "📎 Document",
    }
    label = labels.get(kind, "📥 Inquiry")

    try:
        msg_body = f"{label} #{ticket_id}\nMember ID: {uid}\nContent: {text}\n\nTo respond: /ticket {ticket_id}"
        if file_id:
            await send_media(context, leader_id, file_type, file_id, caption=msg_body)
        else:
            await context.bot.send_message(leader_id, msg_body)
        await update.message.reply_text(f"✅ Submission received (Ticket #{ticket_id}). A leader will review it shortly.")
    except Exception:
        await update.message.reply_text(f"Ticket #{ticket_id} logged. Leader notification pending.")

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
    if leader_id not in LEADER_IDS:
        return

    try:
        ticket_id = int(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /ticket <ticket_id>")
        return

    ticket = get_ticket(ticket_id)
    if not ticket:
        await update.message.reply_text("Error: Ticket ID not found.")
        return

    target_uid, _, status = ticket

    if status != 'open':
        await update.message.reply_text("Notice: This ticket has already been resolved and closed.")
        return

    # Enforce Leader Isolation
    if get_assigned_leader(target_uid) != leader_id:
        await update.message.reply_text("Access Denied: You are not authorized to communicate with this member.")
        return

    context.user_data["reply_uid"] = target_uid
    await update.message.reply_text(f"Active Session: Replying to Ticket #{ticket_id} (Member ID: {target_uid}). Enter message:")

async def close_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    leader_id = update.effective_user.id
    if leader_id not in LEADER_IDS:
        return

    try:
        ticket_id = int(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /close <ticket_id>")
        return

    ticket = get_ticket(ticket_id)
    if not ticket:
        await update.message.reply_text("Error: Ticket ID not found.")
        return

    target_uid, _, status = ticket

    if get_assigned_leader(target_uid) != leader_id:
        await update.message.reply_text("Access Denied: You are not authorized to manage this ticket.")
        return

    if status == 'closed':
        await update.message.reply_text("Notice: Ticket is already marked closed.")
        return

    with sqlite3.connect("bot_data.db") as conn:
        conn.execute("UPDATE tickets SET status='closed' WHERE id=?", (ticket_id,))

    await update.message.reply_text(f"✅ Ticket #{ticket_id} has been marked as resolved.")
    try:
        await context.bot.send_message(
            target_uid,
            f"Notice: Your support request (Ticket #{ticket_id}) has been marked as resolved by your fellowship leader."
        )
    except Exception:
        pass

async def msg_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    leader_id = update.effective_user.id
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

    # Enforce Leader Isolation
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
        conn.execute("UPDATE members SET assigned_leader=? WHERE user_id=?", (new_leader, target_uid))
        conn.execute("UPDATE tickets SET leader_id=? WHERE uid=? AND status='open'", (new_leader, target_uid))

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
            t_id, t_kind, t_msg = active_t
            await context.bot.send_message(
                new_leader,
                f"📌 Transfer Received: Member ID {target_uid} assigned to you.\n"
                f"Active Ticket #{t_id} [{t_kind}]:\n\"{t_msg}\"\n\n"
                f"Reply via: /ticket {t_id}"
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
our message and I'll pass it along.")
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
        "prayer_request": "🙏 Prayer Request",
        "photo": "🖼️ Photo",
        "voice": "🎤 Voice message",
        "document": "📎 File",
    }
    label = labels.get(kind, "📥 Message")

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
        await update.message.reply_text("✅ Sent. A fellowship leader will follow up with you.")
    except Exception:
        await update.message.reply_text("Saved, but the leader appears to be offline right now.")

# ----------------------------
# RESOURCE HELPER (member browsing)
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

    # Only the member's CURRENT leader may reply — this stops an old leader
    # from still messaging someone who has since been transferred away.
    current_leader = get_assigned_leader(target_uid)
    if current_leader != leader_id:
        await update.message.reply_text(
            "❌ You're not currently assigned to this member — they were transferred to another leader.\n"
            "Use /transfer if they need to be moved back to you."
        )
        return

    context.user_data["reply_uid"] = target_uid
    await update.message.reply_text(
        f"Replying to member {target_uid}. Send text, a photo, a voice note, or a file now:"
    )

async def msg_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /msg <user_id> <text> — lets a leader START a conversation with a
    newly assigned member directly, without waiting for a ticket to
    exist (a fresh assignment has no ticket yet, so /ticket <n> has
    nothing to reply to).
    """
    leader_id = update.effective_user.id
    if leader_id not in LEADER_IDS:
        return

    if len(context.args) < 2:
        await update.message.reply_text("Usage: /msg <user_id> <message>")
        return

    try:
        target_uid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Usage: /msg <user_id> <message>")
        return

    if get_assigned_leader(target_uid) != leader_id:
        await update.message.reply_text(
            "❌ You're not currently assigned to this member, so you can't message them directly."
        )
        return

    text = " ".join(context.args[1:])
    try:
        await context.bot.send_message(target_uid, f"✝️ Fellowship Leader:\n{text}")
        await update.message.reply_text("✅ Message sent.")
    except Exception:
        await update.message.reply_text("❌ Failed to send. The member may have blocked the bot, or hasn't started the bot yet.")

async def leader_text_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    acting_leader = update.effective_user.id
    uid = context.user_data.pop("reply_uid")

    if get_assigned_leader(uid) != acting_leader:
        await update.message.reply_text(
            "❌ Not sent — this member was reassigned to another leader before you replied."
        )
        return

    text = update.message.text
    try:
        await context.bot.send_message(uid, f"✝️ Fellowship Leader:\n{text}")
        await update.message.reply_text("✅ Reply sent.")
    except Exception:
        await update.message.reply_text("❌ Failed to send. The member may have blocked the bot.")

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
            target_uid, "🔄 You've been transferred to a new fellowship leader. They'll be in touch."
        )
    except Exception:
        pass

    if old_leader and old_leader != new_leader:
        try:
            await context.bot.send_message(
                old_leader,
                f"⚠️ Member {target_uid} was transferred to another leader.\n"
                f"You are no longer assigned to them and can't reply to their tickets anymore."
            )
        except Exception:
            pass

    try:
        await context.bot.send_message(new_leader, f"📌 Member {target_uid} was transferred to you.")
    except Exception:
        pass

    await update.message.reply_text(f"✅ Member {target_uid} transferred to leader {new_leader}.")

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
            await context.bot.send_message(mid, f"📢 Announcement:\n{text}")
            sent += 1
        except Exception:
            failed += 1

    await update.message.reply_text(f"✅ Broadcast sent to {sent} members. ({failed} failed/blocked.)")

# ----------------------------
# LEADER: resource upload flow
# ----------------------------
async def addsermon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in LEADER_IDS:
        return
    context.user_data["awaiting_resource_cat"] = "sermons"
    await update.message.reply_text("Send the sermon now — as a photo, voice note, or file.")

async def adddevotional(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in LEADER_IDS:
        return
    context.user_data["awaiting_resource_cat"] = "devotionals"
    await update.message.reply_text("Send the devotional now — as a photo, voice note, or file.")

async def addhymn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in LEADER_IDS:
        return
    context.user_data["awaiting_resource_cat"] = "hymns"
    await update.message.reply_text("Send the hymn now — as a photo, voice note, or file.")

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
        await update.message.reply_text(f"📜 History for {uid}:\n{txt}" if txt else "No history.")
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
app.add_handler(CommandHandler("msg", msg_member))
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
