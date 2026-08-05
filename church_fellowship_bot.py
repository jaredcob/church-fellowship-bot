import sqlite3
import random
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
TOKEN = "8292837449:AAFViyStd4dFK6ZX-UckF95RqS019_WxAKo"          # <--- put your BotFather token here
LEADER_IDS = [6555910081, 8399604250]  # <--- Telegram user_ids of pastors / elders / fellowship leaders

# The Web App (Mini App) you host and register in /myapps or Bot Settings > Menu Button.
# It must be served over HTTPS. Example: a GitHub Pages / Vercel / Netlify link.
WEBAPP_URL = "https://yourdomain.com/church-app/"

LEADER_LAST_TICKETS = {8885900780}

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

    # --- PRAYER REQUEST ---
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
# SET THE MENU BUTTON TO OPEN THE WEB APP GLOBALLY (optional, one-time)
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
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, central_message_handler))

print("Church fellowship bot is running...")
app.run_polling()
