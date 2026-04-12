import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import ContextTypes

from src.core.config import settings
from src.core.context import get_tenant_id
from src.db.session import async_session
from src.services import analytics, sheets
from src.services.parser import parse_order_message
from src.services.order_service import process_telegram_order
from src.services import tenant_service
from sqlalchemy import select
from src.db.models import PlatformEnum, Order, Payment, PaymentStatusEnum
from src.services import config_service
from src.services.config_service import SCHEDULE_JOBS
from src.services.sheets import check_google_sheets_connection
from src.bot.bot_manager import bot_manager

from src.auth.roles import (
    ADMIN_ROLES,
    require_admin,
    require_superadmin,
    require_moderator_or_admin,
    require_spreadsheet,
    generate_invite_code,
    generate_admin_invite_code,
    redeem_invite_code,
    add_moderator,
    set_ban_status,
    get_all_moderators,
    get_user_role,
    get_tenant_admin,
    remove_tenant_admin,
    RoleEnum
)

logger = logging.getLogger(__name__)

def _build_invite_link(bot_username: str | None, code: str) -> str | None:
    if not bot_username:
        return None
    return f"https://t.me/{bot_username}?start=join-{code}"

def _extract_join_code_from_start(args: list[str]) -> str | None:
    if not args:
        return None
    payload = args[0].strip()
    lowered = payload.lower()
    if lowered.startswith("join-") or lowered.startswith("join_"):
        return payload[5:]
    return None

async def _send_admin_home(update: Update, role: RoleEnum) -> None:
    if role == RoleEnum.SUPERADMIN:
        from telegram import ReplyKeyboardRemove
        await update.effective_message.reply_text("📌 Superadmin Mode Active.", reply_markup=ReplyKeyboardRemove())
        text = "Welcome back, Owner!\n\nThis is the Superadmin control panel. You can manage your clients, active bots, and platform configuration here."
        await update.effective_message.reply_text(
            text,
            reply_markup=get_superadmin_menu_keyboard(),
            parse_mode="Markdown",
        )
    else:
        sheet_name = await config_service.get_active_sheet_name()
        if not sheet_name:
            # Re-use the manage_sheets logic but as a welcome screen
            await _send_spreadsheet_setup_needed(update, role)
            return

        await update.effective_message.reply_text("📌 Quick access pinned below.", reply_markup=get_persistent_keyboard())
        text = "Welcome to the Multi-Platform Order Tracking Agent 🤖\n\nPlease select an option below:"
        await update.effective_message.reply_text(
            text,
            reply_markup=get_main_menu_keyboard(),
            parse_mode="Markdown",
        )

async def _send_spreadsheet_setup_needed(update: Update, role: RoleEnum) -> None:
    """Shows the spreadsheet connection requirement screen with instructions."""
    email = await _get_service_account_email()
    
    text = (
        "👋 **Welcome! Let's get started...**\n\n"
        "To use this bot, you first need to link a **Google Spreadsheet**. "
        "This ensures all your orders are safely backed up in real-time.\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "📍 **Quick Setup Guide:**\n"
        "1️⃣ Open Google Sheets and create a blank spreadsheet.\n"
        "2️⃣ Click the blue **Share** button (top-right).\n"
        "3️⃣ Add this bot's email and give it **Editor** access:\n"
        f"`{email}`\n"
        "4️⃣ Copy the spreadsheet URL and paste it here.\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Tap the button below to submit your link:"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Set/Change Connection", callback_data="cmd_prompt_sheet_name")],
        [InlineKeyboardButton("⚙️ Open Settings", callback_data="cmd_settings")]
    ])
    
    if update.effective_message:
        await update.effective_message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)
    elif update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)

async def _get_service_account_email() -> str:
    """Helper to fetch the service account email from config or file."""
    import json as _json
    try:
        if settings.GSHEETS_CONFIG_JSON:
            # Handle potential double-quotes from env vars
            raw_json = settings.GSHEETS_CONFIG_JSON.strip()
            if raw_json.startswith('"') and raw_json.endswith('"'):
                raw_json = raw_json[1:-1].replace('\\"', '"')
            _creds = _json.loads(raw_json)
        else:
            with open("service_account.json", "r") as _f:
                _creds = _json.load(_f)
        return _creds.get("client_email", "Not Found in JSON")
    except Exception as e:
        logger.error(f"Error reading service account email: {e}")
        return "Not Found (Check GSHEETS_CONFIG_JSON)"

async def _complete_invite_join(update: Update, code: str) -> None:
    user_id = str(update.effective_user.id)
    full_name = update.effective_user.full_name or "Moderator"
    result = await redeem_invite_code(user_id, full_name, code)

    if result == RoleEnum.ADMIN:
        sheet_name = await config_service.get_active_sheet_name()
        if not sheet_name:
            await _send_spreadsheet_setup_needed(update, RoleEnum.ADMIN)
            return

        welcome_msg = (
            f"✅ **Welcome {full_name}!** You have been added as an Admin.\n\n"
            "You now have full access to this client's workspace.\n\n"
            "Tap the button below to open your dashboard."
        )
        await update.effective_message.reply_text("📌 Quick access pinned below.", reply_markup=get_persistent_keyboard())
        menu_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("📊 Open Dashboard", callback_data="cmd_main_menu")]])
        await update.effective_message.reply_text(welcome_msg, parse_mode="Markdown", reply_markup=menu_keyboard)
        return

    if result == RoleEnum.MODERATOR:
        welcome_msg = (
            f"✅ **Welcome {full_name}!** You have successfully joined as a Moderator.\n\n"
            "Here is how to use the bot:\n"
            "Whenever you receive a new order, simply send a message in this exact format:\n\n"
            "`#ORDER`\n"
            "`Product: Exact Product Name`\n"
            "`Qty: 1`\n"
            "`Price: 500`\n"
            "`Phone: 017XXXXXXXX`\n\n"
            "I will save it and automatically update the Google Sheets database!"
        )
        await update.effective_message.reply_text("📌 Quick access pinned below.", reply_markup=get_moderator_persistent_keyboard())
        await update.effective_message.reply_text(welcome_msg, parse_mode="Markdown")
        return

    await update.effective_message.reply_text(f"❌ Failed to join: {result}")

def get_persistent_keyboard():
    """Persistent reply keyboard pinned at the bottom of the chat for Admin."""
    return ReplyKeyboardMarkup([["🏠 Main Menu"]], resize_keyboard=True, is_persistent=True)


def get_moderator_persistent_keyboard():
    """Persistent reply keyboard pinned at the bottom of the chat for Moderators."""
    return ReplyKeyboardMarkup(
        [
            ["🏠 Main Menu", "📊 My Stats Today"],
            ["📦 Check Stock", "🔍 Search My Orders"],
            ["⚠️ Report Low Stock"],
        ],
        resize_keyboard=True,
        is_persistent=True
    )


def get_superadmin_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("📋 List All Clients", callback_data="cmd_sa_list_clients")],
        [InlineKeyboardButton("➕ Add New Client", callback_data="cmd_sa_add_client")]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_main_menu_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("📊 Today's Sales", callback_data="cmd_today_all"),
            InlineKeyboardButton("🌍 Web Dashboard", url=settings.DASHBOARD_URL)
        ],
        [
            InlineKeyboardButton("📅 Weekly", callback_data="cmd_weekly"),
            InlineKeyboardButton("📅 Monthly", callback_data="cmd_monthly")
        ],
        [
            InlineKeyboardButton("📈 Growth", callback_data="cmd_growth"),
            InlineKeyboardButton("🚨 Alerts", callback_data="cmd_alerts")
        ],
        [
            InlineKeyboardButton("📋 Recent Orders", callback_data="cmd_orders_all"),
            InlineKeyboardButton("🔍 Search Orders", callback_data="cmd_search_prompt")
        ],
        [InlineKeyboardButton("🏆 Top Product", callback_data="cmd_top")],
        [InlineKeyboardButton("⏳ Pending Orders", callback_data="cmd_pending")],
        [
            InlineKeyboardButton("📦 Stock Overview", callback_data="cmd_stock"),
            InlineKeyboardButton("👥 Team Stats",     callback_data="cmd_team_stats")
        ],
        [
            InlineKeyboardButton("📊 Google Sheet", callback_data="cmd_check_sheets"),
            InlineKeyboardButton("⚙️ Settings", callback_data="cmd_settings")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_moderator_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("📊 My Stats Today", callback_data="cmd_my_stats")],
        [
            InlineKeyboardButton("📦 Check Stock",      callback_data="cmd_mod_stock"),
            InlineKeyboardButton("🔍 Search My Orders", callback_data="cmd_mod_search_prompt"),
        ],
        [InlineKeyboardButton("⚠️ Report Low Stock", callback_data="cmd_mod_lowstock_prompt")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_settings_keyboard():
    keyboard = [
        [InlineKeyboardButton("⏰ Schedule & Alerts", callback_data="cmd_schedule_menu")],
        [InlineKeyboardButton("🎟️ Generate Invite Link", callback_data="cmd_generate_invite")],
        [InlineKeyboardButton("👥 List Moderators", callback_data="cmd_list_mods")],
        [InlineKeyboardButton("👑 Admin Management", callback_data="cmd_admin_mgmt")],
        [InlineKeyboardButton("📊 Manage Spreadsheet", callback_data="cmd_manage_sheets")],
        [InlineKeyboardButton("🏠 Back to Main Menu", callback_data="cmd_main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)


# ---------------------------------------------------------------------------
# Schedule Settings UI helpers
# ---------------------------------------------------------------------------

async def _build_schedule_overview() -> tuple[str, InlineKeyboardMarkup]:
    """Return the schedule overview text and its navigation keyboard."""
    lines = [
        "⏰ *Schedule & Alert Settings*",
        "",
        "📍 All times use *Asia/Dhaka* timezone _(GMT+6)_",
        "Tap any item below to configure its time or toggle it on/off",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        "*📋 Reports* — Always Active",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    for job_id in ["daily_report", "weekly_report", "monthly_report"]:
        cfg = SCHEDULE_JOBS[job_id]
        t = await config_service.get_job_time(job_id)
        lines.append(f"  ✅ {cfg['name']}  →  `{t}`  _({cfg['recurrence']})_")

    lines.extend([
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        "*🔔 Alerts* — Can be enabled or disabled",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
    ])
    for job_id in ["sales_drop_alert", "trending_product_alert",
                   "growth_comparison_report", "stock_prediction_alert"]:
        cfg = SCHEDULE_JOBS[job_id]
        t = await config_service.get_job_time(job_id)
        enabled = await config_service.get_job_enabled(job_id)
        dot = "🟢" if enabled else "🔴"
        lines.append(f"  {dot} {cfg['name']}  →  `{t}`")

    text = "\n".join(lines)

    keyboard: list[list[InlineKeyboardButton]] = []
    # Report buttons — show current time
    for job_id in ["daily_report", "weekly_report", "monthly_report"]:
        cfg = SCHEDULE_JOBS[job_id]
        t = await config_service.get_job_time(job_id)
        keyboard.append([InlineKeyboardButton(
            f"{cfg['name']} — {t}",
            callback_data=f"cmd_sched_job_{job_id}"
        )])
    # Alert buttons — show time + on/off dot
    for job_id in ["sales_drop_alert", "trending_product_alert",
                   "growth_comparison_report", "stock_prediction_alert"]:
        cfg = SCHEDULE_JOBS[job_id]
        t = await config_service.get_job_time(job_id)
        enabled = await config_service.get_job_enabled(job_id)
        dot = "🟢" if enabled else "🔴"
        keyboard.append([InlineKeyboardButton(
            f"{dot} {cfg['name']} — {t}",
            callback_data=f"cmd_sched_job_{job_id}"
        )])
    keyboard.append([InlineKeyboardButton("🔙 Back to Settings", callback_data="cmd_settings")])
    return text, InlineKeyboardMarkup(keyboard)


async def _build_job_detail(job_id: str) -> tuple[str, InlineKeyboardMarkup]:
    """Return the detail card text and action keyboard for a single job."""
    cfg = SCHEDULE_JOBS[job_id]
    t = await config_service.get_job_time(job_id)
    enabled_key = cfg.get("enabled_key")

    lines = [
        f"*{cfg['name']}*",
        f"_{cfg['description']}_",
        "",
        f"📅 *Recurrence:*  {cfg['recurrence']}",
        f"⏰ *Current Time:*  `{t}`  _(Asia/Dhaka, GMT+6)_",
    ]

    if enabled_key:
        enabled = await config_service.get_job_enabled(job_id)
        status = "🟢 *Enabled*" if enabled else "🔴 *Disabled*"
        lines.append(f"🔔 *Status:*  {status}")
    else:
        lines.append("🔔 *Status:*  ✅ Always Active _(cannot be disabled)_")

    lines.extend([
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        "*How to change the time:*",
        "1\\. Tap *Change Time* below",
        "2\\. Send the new time in `HH:MM` 24-hour format",
        "",
        "*Examples:*",
        "  `09:00`  →  9:00 AM",
        "  `14:30`  →  2:30 PM",
        "  `21:00`  →  9:00 PM",
        "  `23:59`  →  11:59 PM",
    ])
    text = "\n".join(lines)

    keyboard: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton("⏰ Change Time", callback_data=f"cmd_sched_settime_{job_id}")],
    ]
    if enabled_key:
        enabled = await config_service.get_job_enabled(job_id)
        if enabled:
            keyboard.append([InlineKeyboardButton(
                "🔴 Disable This Alert", callback_data=f"cmd_sched_toggle_{job_id}"
            )])
        else:
            keyboard.append([InlineKeyboardButton(
                "🟢 Enable This Alert", callback_data=f"cmd_sched_toggle_{job_id}"
            )])
    keyboard.append([InlineKeyboardButton("🔙 Back to Schedule", callback_data="cmd_schedule_menu")])
    return text, InlineKeyboardMarkup(keyboard)

def get_orders_filter_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("🟦 Facebook Orders", callback_data="cmd_orders_FACEBOOK"),
            InlineKeyboardButton("🟢 WhatsApp Orders", callback_data="cmd_orders_WHATSAPP")
        ],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="cmd_main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_invite_platform_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("🟦 Facebook Moderator", callback_data="cmd_gen_invite_FACEBOOK"),
            InlineKeyboardButton("🟢 WhatsApp Moderator", callback_data="cmd_gen_invite_WHATSAPP")
        ],
        [InlineKeyboardButton("🔙 Back to Settings", callback_data="cmd_settings")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    join_code = _extract_join_code_from_start(context.args)
    if join_code:
        await _complete_invite_join(update, join_code)
        return

    user_id = str(update.effective_user.id)
    role = await get_user_role(user_id)
    if role in ADMIN_ROLES:
        await _send_admin_home(update, role)
        return

    if role == RoleEnum.MODERATOR:
        await update.effective_message.reply_text("ðŸ“Œ Quick access pinned below.", reply_markup=get_moderator_persistent_keyboard())
        await update.effective_message.reply_text(
            "Welcome back! Use the keyboard below to check your stats or send a new `#ORDER` anytime.",
            parse_mode="Markdown",
        )
        return

    await update.effective_message.reply_text(
        "Welcome. You need an invite from the owner or client admin before you can access this bot.\n\n"
        "If you already have a code, send `/join YOUR-CODE`.",
        parse_mode="Markdown",
    )
    return
    # Pin the persistent keyboard at the bottom
    await update.effective_message.reply_text("📌 Quick access pinned below.", reply_markup=get_persistent_keyboard())
    # Show the inline dashboard
    await update.effective_message.reply_text(
        "Welcome to the Multi-Platform Order Tracking Agent 🤖\n\nPlease select an option below:",
        reply_markup=get_main_menu_keyboard()
    )

@require_admin
async def chatid_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    await update.effective_message.reply_text(
        f"🆔 Your Chat ID is: `{chat_id}`\n\nAdd this to your `.env` file as:\n`TELEGRAM_CHAT_ID=\"{chat_id}\"`",
        parse_mode="Markdown"
    )

# --- Role Management Commands ---

@require_admin
async def generate_invite_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = "🎟️ **Select Platform**\n\nThe moderator will be automatically tagged with this platform:"
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, parse_mode="Markdown", reply_markup=get_invite_platform_keyboard())
    else:
        await update.effective_message.reply_text(msg, parse_mode="Markdown", reply_markup=get_invite_platform_keyboard())

async def _do_generate_invite(update: Update, context: ContextTypes.DEFAULT_TYPE, platform: PlatformEnum):
    code = await generate_invite_code(platform)
    bot_username = getattr(context.bot, "username", None)
    invite_link = _build_invite_link(bot_username, code)
    plat_icon = "🟦 Facebook" if platform == PlatformEnum.FACEBOOK else "🟢 WhatsApp"
    
    admin_msg = f"🎟️ **New {plat_icon} Invite Generated!**\n\nForward or copy the message below to your new moderator:"
    
    bot_display = bot_username.replace("_", r"\_") if bot_username else "bot"
    step_one = f"**Step 1:** To connect your account, open the bot here ðŸ‘‰ @{bot_display} and send this exact code:\n`/join {code}`"
    if invite_link:
        step_one = (
            f"**Step 1:** Click this access link:\n{invite_link.replace('_', r'\_')}\n\n"
            f"Or open @{bot_display} and send:\n`/join {code}`"
        )

    forward_msg = (
        f"👋 **Welcome to the team!**\n"
        f"You have been invited to access the Order Tracking Bot as a {plat_icon} Moderator.\n\n"
        f"{step_one}\n\n"
        f"**Step 2:** After joining, whenever you receive a new order, simply copy-paste and fill out this format here:\n\n"
        f"`#ORDER`\n"
        f"`Product: (Write Name Here)`\n"
        f"`Qty: 1`\n"
        f"`Price: 500`\n"
        f"`Phone: 017XXXXXXXX`\n"
        f"`Status: PAID` _(optional, defaults to PENDING)_"
    )
    
    # Add Main Menu button to the forwarded message for easier navigation
    menu_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="cmd_main_menu")]])
    
    if update.callback_query:
        await update.callback_query.edit_message_text(admin_msg, parse_mode="Markdown", reply_markup=get_settings_keyboard())
        await update.callback_query.message.reply_text(forward_msg, parse_mode="Markdown", reply_markup=menu_keyboard)
    else:
        await update.effective_message.reply_text(admin_msg, parse_mode="Markdown", reply_markup=get_settings_keyboard())
        await update.effective_message.reply_text(forward_msg, parse_mode="Markdown", reply_markup=menu_keyboard)

    if invite_link:
        target_message = update.callback_query.message if update.callback_query else update.effective_message
        await target_message.reply_text(f"Direct join link:\n{invite_link}")

async def join_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.effective_message.reply_text("❌ Please provide an invite code. Example: `/join INV-ABCD123`")
        return
        
    await _complete_invite_join(update, context.args[0])
    return

    code = context.args[0]
    user_id = str(update.effective_user.id)
    full_name = update.effective_user.full_name or "Moderator"
    
    result = await redeem_invite_code(user_id, full_name, code)
    if result == RoleEnum.ADMIN:
        welcome_msg = (
            f"✅ **Welcome {full_name}!** You have been added as an Admin.\n\n"
            "You now have full access to the SME Management dashboard.\n\n"
            "**What you can do:**\n"
            "• View daily, weekly and monthly sales reports\n"
            "• Monitor top products and revenue breakdown\n"
            "• Check pending orders and stock alerts\n"
            "• Manage moderators (invite, ban, unban)\n"
            "• Connect and manage Google Sheets\n\n"
            "Tap the button below to open your dashboard."
        )
        # Pin the persistent keyboard first, then show the welcome
        await update.effective_message.reply_text("📌 Quick access pinned below.", reply_markup=get_persistent_keyboard())
        menu_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("📊 Open Dashboard", callback_data="cmd_main_menu")]])
        await update.effective_message.reply_text(welcome_msg, parse_mode="Markdown", reply_markup=menu_keyboard)
    elif result == RoleEnum.MODERATOR:
        welcome_msg = (
            f"✅ **Welcome {full_name}!** You have successfully joined as a Moderator.\n\n"
            "Here is how to use the bot:\n"
            "Whenever you receive a new order, simply send a message in this exact format:\n\n"
            "`#ORDER`\n"
            "`Product: Exact Product Name`\n"
            "`Qty: 1`\n"
            "`Price: 500`\n"
            "`Phone: 017XXXXXXXX`\n\n"
            "I will save it and automatically update the Google Sheets database!"
        )
        # Show persistent keyboard for moderator
        await update.effective_message.reply_text("📌 Quick access pinned below.", reply_markup=get_moderator_persistent_keyboard())
        await update.effective_message.reply_text(welcome_msg, parse_mode="Markdown")


    else:
        await update.effective_message.reply_text(f"❌ Failed to join: {result}")

@require_superadmin
async def new_client_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    raw = " ".join(context.args).strip()
    if not raw:
        await update.effective_message.reply_text(
            "Usage:\n<code>/newclient Lux | 123456:ABCDEF | optional-sheet-id-or-name</code>\n\n"
            "The sheet part is optional.",
            parse_mode="HTML",
        )
        return

    parts = [part.strip() for part in raw.split("|")]
    if len(parts) < 2:
        await update.effective_message.reply_text(
            "Please provide at least the client name and bot token.\n\n"
            "Example:\n<code>/newclient Lux | 123456:ABCDEF | Lux Orders</code>",
            parse_mode="HTML",
        )
        return

    client_name = parts[0]
    bot_token = parts[1]
    google_sheet_name = parts[2] if len(parts) > 2 else None

    try:
        tenant = await tenant_service.create_tenant(client_name, bot_token, google_sheet_name)
    except ValueError as exc:
        await update.effective_message.reply_text(f"❌ {exc}")
        return

    admin_code = await generate_admin_invite_code(str(tenant.id))
    app = await bot_manager.start_tenant_bot(tenant)
    bot_username = bot_manager.get_bot_username(str(tenant.id))
    invite_link = _build_invite_link(bot_username, admin_code) if admin_code else None

    status_line = "✅ Bot started successfully." if app else "⚠️ Client saved, but the bot could not be started. Please verify the token."
    bot_line = f"@{bot_username}" if bot_username else "<i>Username unavailable until the bot starts successfully</i>"

    lines = [
        f"✅ <b>Client Created:</b> {tenant.name}",
        f"Client ID: <code>{tenant.id}</code>",
        f"Bot: {bot_line}",
        status_line,
    ]
    if tenant.google_sheet_name:
        lines.append(f"Sheet: <code>{tenant.google_sheet_name}</code>")
    if admin_code:
        lines.append("")
        lines.append("<b>Client Admin Access</b>")
        if invite_link:
            lines.append(invite_link)
        lines.append(f"Fallback code: <code>/join {admin_code}</code>")
    else:
        lines.append("")
        lines.append("⚠️ This client already has an admin, so no new admin invite was created.")

    await update.effective_message.reply_text("\n".join(lines), parse_mode="HTML")


@require_superadmin
async def list_clients_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    clients = await tenant_service.list_tenants()
    if not clients:
        await update.effective_message.reply_text("No clients found yet. Use `/newclient` to create the first one.", parse_mode="Markdown")
        return

    lines = ["📋 *Client List*"]
    for index, client in enumerate(clients, start=1):
        status = "Active" if client["is_active"] else "Inactive"
        sheet_name = client["google_sheet_name"] or "Not set"
        lines.append(
            f"\n{index}. *{client['name']}*\n"
            f"ID: `{client['id']}`\n"
            f"Status: {status}\n"
            f"Admins: {client['admin_count']} | Moderators: {client['moderator_count']}\n"
            f"Sheet: `{sheet_name}`"
        )

    await update.effective_message.reply_text("\n".join(lines), parse_mode="Markdown")


@require_admin
async def add_mod_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.effective_message.reply_text("❌ Please provide a user ID. Example: `/add_moderator 12345678`")
        return
        
    user_id = context.args[0]
    success = await add_moderator(user_id)
    if success:
        await update.effective_message.reply_text(f"✅ User `{user_id}` added as Moderator.", parse_mode="Markdown")
    else:
        await update.effective_message.reply_text(f"⚠️ User `{user_id}` is already registered.", parse_mode="Markdown")

@require_admin
async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.effective_message.reply_text("❌ Please provide an ID. Example: `/ban 12345678`")
        return
        
    user_id = context.args[0]
    
    mods = await get_all_moderators()
    user_name = next((m['name'] for m in mods if m['id'] == user_id), "Unknown")
    
    success = await set_ban_status(user_id, True)
    if success:
        await update.effective_message.reply_text(f"✅ Moderator **{user_name}** (`{user_id}`) has been BANNED.", parse_mode="Markdown")
        await list_mod_command(update, context)
    else:
        await update.effective_message.reply_text(f"❌ Could not ban `{user_id}` (not found or is an Admin).", parse_mode="Markdown")

@require_admin
async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.effective_message.reply_text("❌ Please provide an ID. Example: `/unban 12345678`")
        return
        
    user_id = context.args[0]
    
    mods = await get_all_moderators()
    user_name = next((m['name'] for m in mods if m['id'] == user_id), "Unknown")
    
    success = await set_ban_status(user_id, False)
    if success:
        await update.effective_message.reply_text(f"✅ Moderator **{user_name}** (`{user_id}`) has been UNBANNED.", parse_mode="Markdown")
        await list_mod_command(update, context)
    else:
        await update.effective_message.reply_text(f"❌ Could not unban `{user_id}` (not found or is an Admin).", parse_mode="Markdown")

@require_admin
async def list_mod_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    mods = await get_all_moderators()
    
    if not mods:
        text = "No moderators found."
        keyboard_buttons = [[InlineKeyboardButton("🔙 Back to Settings", callback_data="cmd_settings")]]
        keyboard = InlineKeyboardMarkup(keyboard_buttons)
    else:
        text = "📋 **List of Moderators:**\n\n"
        keyboard_buttons = []
        
        for idx, m in enumerate(mods, 1):
            status = "🚫 Banned" if m['is_banned'] else "✅ Active"
            if m['platform'] == PlatformEnum.FACEBOOK:
                plat_icon = "🟦 Facebook"
            elif m['platform'] == PlatformEnum.WHATSAPP:
                plat_icon = "🟢 WhatsApp"
            else:
                plat_icon = "🌐 General"
                
            text += f"{idx}. 👤 **{m['name']}**\n   ID: `{m['id']}` | {plat_icon} | {status}\n\n"
            
        keyboard_buttons.append([InlineKeyboardButton("⚙️ Manage Bans", callback_data="cmd_manage_bans")])
        keyboard_buttons.append([InlineKeyboardButton("🔙 Back to Settings", callback_data="cmd_settings")])
        keyboard = InlineKeyboardMarkup(keyboard_buttons)
        
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)
    else:
        await update.effective_message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)

# --- Analytics Commands (Admin Only) ---

async def _send_today_sales(update: Update, platform: PlatformEnum = None):
    async with async_session() as session:
        stats = await analytics.get_daily_sales(session, platform=platform)
        sales = stats["total_sales"]
        orders = stats["total_orders"]
        
        if platform == PlatformEnum.FACEBOOK:
            msg = f"🟦 *Facebook Sales Today:*\nTotal Sales: ৳{sales:,.2f}\nTotal Orders: {orders}"
        elif platform == PlatformEnum.WHATSAPP:
            msg = f"🟢 *WhatsApp Sales Today:*\nTotal Sales: ৳{sales:,.2f}\nTotal Orders: {orders}"
        else:
            msg = f"📊 *Total Combined Sales Today:*\nTotal Sales: ৳{sales:,.2f}\nTotal Orders: {orders}"
            
        await update.effective_message.reply_markdown(msg, reply_markup=get_main_menu_keyboard())

async def _send_recent_orders(update: Update, platform: PlatformEnum = None, edit: bool = False, offset: int = 0):
    limit = 10
    async with async_session() as session:
        orders = await analytics.get_recent_orders(session, limit=limit + 1, platform=platform, offset=offset)

    has_next = len(orders) > limit
    if has_next:
        orders = orders[:limit]

    title = "📋 *Recent Orders*"
    if platform == PlatformEnum.FACEBOOK:
        title = "🟦 *Recent Facebook Orders*"
    elif platform == PlatformEnum.WHATSAPP:
        title = "🟢 *Recent WhatsApp Orders*"

    plat_key = platform.value if platform else "all"

    if not orders:
        text = f"{title}\n\nNo orders found."
    else:
        text = f"{title} (#{offset + 1}–#{offset + len(orders)})\n\n"
        for o in orders:
            text += f"ID: {o.order_id} - {o.product_name} (BDT {o.price})\nPlatform: {o.platform.value}\n---\n"

    # Build pagination nav row
    nav_buttons = []
    if offset > 0:
        nav_buttons.append(InlineKeyboardButton("◀️ Prev", callback_data=f"cmd_orders_{plat_key}_{max(0, offset - limit)}"))
    if has_next:
        nav_buttons.append(InlineKeyboardButton("Next ▶️", callback_data=f"cmd_orders_{plat_key}_{offset + limit}"))

    keyboard = [
        [
            InlineKeyboardButton("🟦 Facebook Orders", callback_data="cmd_orders_FACEBOOK_0"),
            InlineKeyboardButton("🟢 WhatsApp Orders", callback_data="cmd_orders_WHATSAPP_0")
        ],
    ]
    if nav_buttons:
        keyboard.append(nav_buttons)
    keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data="cmd_main_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    if edit:
        await update.effective_message.edit_text(text, parse_mode="Markdown", reply_markup=reply_markup)
    else:
        await update.effective_message.reply_markdown(text, reply_markup=reply_markup)

@require_admin
@require_spreadsheet
async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_today_sales(update, platform=None)

@require_admin
@require_spreadsheet
async def orders_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_recent_orders(update, platform=None)

def _order_card_text(order) -> str:
    """Formats a single order as a readable text block."""
    status_icon = "✅" if order.payment_status == PaymentStatusEnum.PAID else "⏳"
    return (
        f"🆔 `{order.order_id}`\n"
        f"📦 {order.product_name}\n"
        f"🔢 Qty: {order.quantity} | 💰 ৳{order.price}\n"
        f"📱 Phone: {order.phone_number or '—'}\n"
        f"🌐 {order.platform.value} | {status_icon} {order.payment_status.value}\n"
        f"🕐 {order.timestamp.strftime('%d %b %Y, %I:%M %p')}"
    )

def _order_action_keyboard(order_id: str) -> InlineKeyboardMarkup:
    """Inline buttons for edit and cancel on an order card."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✏️ Edit", callback_data=f"cmd_edit_{order_id}"),
            InlineKeyboardButton("❌ Cancel Order", callback_data=f"cmd_cancel_{order_id}")
        ]
    ])

def _mod_order_action_keyboard(order_id: str) -> InlineKeyboardMarkup:
    """Inline buttons for moderator: edit and mark as paid on their own orders."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✏️ Edit", callback_data=f"cmd_edit_{order_id}"),
            InlineKeyboardButton("✅ Mark as Paid", callback_data=f"cmd_markpaid_{order_id}")
        ]
    ])

@require_admin
@require_spreadsheet
async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Search orders by product name, phone, or order ID. Usage: /search <query>"""
    if not context.args:
        await update.effective_message.reply_text(
            "🔍 *Order Search*\n\nUsage: `/search <query>`\n\nYou can search by:\n"
            "• Product name  (e.g. `/search Nike`)\n"
            "• Phone number  (e.g. `/search 01712`)\n"
            "• Order ID      (e.g. `/search ORD-225`)",
            parse_mode="Markdown"
        )
        return

    query = " ".join(context.args).strip()
    async with async_session() as session:
        orders = await analytics.search_orders(session, query)

    if not orders:
        await update.effective_message.reply_text(
            f"🔍 No orders found for *\"{query}\"*.", parse_mode="Markdown",
            reply_markup=get_main_menu_keyboard()
        )
        return

    await update.effective_message.reply_text(
        f"🔍 *{len(orders)} result(s) for \"{query}\":*", parse_mode="Markdown"
    )
    for order in orders:
        await update.effective_message.reply_text(
            _order_card_text(order),
            parse_mode="Markdown",
            reply_markup=_order_action_keyboard(order.order_id)
        )

@require_admin
@require_spreadsheet
async def top_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with async_session() as session:
        top_product = await analytics.get_weekly_top_product(session)
        if top_product:
            msg = f"🏆 *Top Product (Last 7 Days)*\n{top_product['product_name']}\nSold: {top_product['quantity']} units"
            await update.effective_message.reply_markdown(msg, reply_markup=get_main_menu_keyboard())
        else:
            await update.effective_message.reply_text("No sales recorded in the last 7 days.", reply_markup=get_main_menu_keyboard())

@require_admin
@require_spreadsheet
async def weekly_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with async_session() as session:
        stats = await analytics.get_weekly_sales(session)
        top = await analytics.get_weekly_top_product(session)
        
        msg = f"📅 *Weekly Sales Report (Last 7 Days)*\n"
        msg += f"Total Sales: ৳{stats['total_sales']:,.2f}\n"
        msg += f"Total Orders: {stats['total_orders']}\n"
        if top:
            msg += f"🏆 Top Product: {top['product_name']} ({top['quantity']} units)"
            
        await update.effective_message.reply_markdown(msg, reply_markup=get_main_menu_keyboard())

@require_admin
@require_spreadsheet
async def monthly_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with async_session() as session:
        stats = await analytics.get_monthly_sales(session)
        top = await analytics.get_monthly_top_product(session)
        
        msg = f"📅 *Monthly Sales Report (Last 30 Days)*\n"
        msg += f"Total Sales: ৳{stats['total_sales']:,.2f}\n"
        msg += f"Total Orders: {stats['total_orders']}\n"
        if top:
            msg += f"🏆 Top Product: {top['product_name']} ({top['quantity']} units)"
            
        await update.effective_message.reply_markdown(msg, reply_markup=get_main_menu_keyboard())

@require_admin
@require_spreadsheet
async def growth_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with async_session() as session:
        predictions = await analytics.get_stock_predictions(session)
        
        if not predictions:
            await update.effective_message.reply_text("No growth data available yet.", reply_markup=get_main_menu_keyboard())
            return
            
        msg = "📈 *Growth & Stock Predictions*\n\n"
        for p in predictions:
            status = "✅"
            if p['days_remaining'] < 7: status = "🚨"
            elif p['days_remaining'] < 14: status = "⚠️"
            
            msg += f"{status} *{p['product_name']}*\n"
            msg += f"Stock: {p['current_stock']} | Velocity: {p['avg_daily_sales']:.1f}/day\n"
            msg += f"Est. Days Left: {p['days_remaining'] if p['days_remaining'] < 900 else 'N/A'}\n\n"
            
        await update.effective_message.reply_markdown(msg, reply_markup=get_main_menu_keyboard())

@require_moderator_or_admin
async def moderator_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = str(update.effective_user.id)
    async with async_session() as session:
        stats = await analytics.get_moderator_stats(session, user_id)
        
        # Simple gamification: Achievement message
        achievement = "Keep it up! 🚀"
        if stats["total_orders"] >= 10:
            achievement = "Superstar! 🌟 You're on fire today!"
        elif stats["total_orders"] >= 5:
            achievement = "Great job! 📈 You're making a real impact!"
        elif stats["total_orders"] > 0:
            achievement = "Nice start! 👍 Let's keep those orders coming!"

        msg = (
            f"📊 **Your Performance Today**\n\n"
            f"✅ **Total Orders:** {stats['total_orders']}\n"
            f"💰 **Total Sales:** ৳{stats['total_sales']:,.2f}\n\n"
            f"_{achievement}_"
        )
        
        if update.callback_query:
            await update.callback_query.edit_message_text(msg, parse_mode="Markdown")
        else:
            await update.effective_message.reply_text(msg, parse_mode="Markdown")


@require_admin
@require_spreadsheet
async def alerts_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with async_session() as session:
        predictions = await analytics.get_stock_predictions(session)
        alerts = [p for p in predictions if p['days_remaining'] < 14 or p['current_stock'] < 5]
        
        if not alerts:
            await update.effective_message.reply_text("✅ No active alerts. All stock levels healthy.", reply_markup=get_main_menu_keyboard())
            return
            
        msg = "🚨 *Active Alerts*\n\n"
        for a in alerts:
            msg += f"• *{a['product_name']}*: Only {a['current_stock']} left! (Runs out in {a['days_remaining']:.1f} days)\n"
            
        await update.effective_message.reply_markdown(msg, reply_markup=get_main_menu_keyboard())

@require_admin
@require_spreadsheet
async def stock_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show all products with current stock levels, sales velocity, and days remaining."""
    async with async_session() as session:
        products = await analytics.get_all_products(session)
        predictions = await analytics.get_stock_predictions(session)

    if not products:
        await update.effective_message.reply_text(
            "📦 *Stock Overview*\n\nNo products tracked yet.\n\n"
            "Products are added automatically when orders are submitted.\n"
            "Use `/setstock <qty> <product>` to set stock levels.",
            parse_mode="Markdown", reply_markup=get_main_menu_keyboard()
        )
        return

    pred_map = {p["product_name"]: p for p in predictions}
    lines = ["📦 *Stock Overview*\n"]
    for product in products:
        p = pred_map.get(product.name, {})
        stock = product.current_stock
        velocity = p.get("avg_daily_sales", 0)
        days = p.get("days_remaining", 999)

        if stock == 0:
            icon = "⚫"
            days_str = "—"
        elif days < 5:
            icon = "🔴"
            days_str = f"{days:.1f}d"
        elif days < 14:
            icon = "🟡"
            days_str = f"{days:.1f}d"
        else:
            icon = "🟢"
            days_str = f"{days:.0f}d" if days < 999 else "∞"

        vel_str = f"{velocity:.1f}/day" if velocity > 0 else "no sales"
        lines.append(f"{icon} *{product.name}*\n   Stock: {stock} | {vel_str} | Left: {days_str}")

    lines.append("\n🔴 Critical  🟡 Low  🟢 OK  ⚫ Not set")
    lines.append("Use `/setstock <qty> <product>` to update stock.")

    await update.effective_message.reply_text(
        "\n".join(lines), parse_mode="Markdown", reply_markup=get_main_menu_keyboard()
    )


@require_admin
async def team_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show per-moderator order and sales stats."""
    async with async_session() as session:
        stats = await analytics.get_all_moderators_stats(session)

    if not stats:
        await update.effective_message.reply_text(
            "👥 *Team Stats*\n\nNo active moderators found.",
            parse_mode="Markdown", reply_markup=get_main_menu_keyboard()
        )
        return

    lines = ["👥 *Team Performance*\n"]
    for idx, m in enumerate(stats, 1):
        plat_icon = {"FACEBOOK": "🟦", "WHATSAPP": "🟢", "TELEGRAM": "🔵"}.get(m["platform"], "🌐")
        lines.append(
            f"{idx}. {plat_icon} *{m['name']}*\n"
            f"   Today:    {m['today_orders']} orders · ৳{m['today_sales']:,.0f}\n"
            f"   7 days:   {m['week_orders']} orders · ৳{m['week_sales']:,.0f}\n"
            f"   All-time: {m['alltime_orders']} orders · ৳{m['alltime_sales']:,.0f}"
        )

    await update.effective_message.reply_text(
        "\n".join(lines), parse_mode="Markdown", reply_markup=get_main_menu_keyboard()
    )


@require_admin
@require_spreadsheet
async def setstock_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Set stock for a product. Usage: /setstock <quantity> <product name>"""
    if not context.args or len(context.args) < 2:
        await update.effective_message.reply_text(
            "❌ Usage: `/setstock <quantity> <product name>`\n\nExample: `/setstock 50 Nike Air Max`",
            parse_mode="Markdown"
        )
        return

    try:
        quantity = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text("❌ Quantity must be a number. Example: `/setstock 50 Nike Air Max`", parse_mode="Markdown")
        return

    product_name = " ".join(context.args[1:]).title()

    async with async_session() as session:
        from sqlalchemy import select
        from src.db.models import Product
        result = await session.execute(select(Product).where(Product.name == product_name))
        product = result.scalar_one_or_none()
        if product:
            product.current_stock = quantity
        else:
            session.add(Product(name=product_name, current_stock=quantity))
        await session.commit()

    await update.effective_message.reply_text(
        f"✅ Stock updated!\n\n*{product_name}*: {quantity} units",
        parse_mode="Markdown",
        reply_markup=get_main_menu_keyboard()
    )

@require_admin
@require_spreadsheet
async def pending_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with async_session() as session:
        orders = await analytics.get_pending_orders(session, limit=5)
        if not orders:
            await update.effective_message.reply_text("✅ No pending orders found.", reply_markup=get_main_menu_keyboard())
            return

        for o in orders:
            text = (
                f"⏳ *Pending Order*\n"
                f"ID: `{o.order_id}`\n"
                f"Product: {o.product_name}\n"
                f"Qty: {o.quantity} | Price: ৳{o.price}\n"
                f"Platform: {o.platform.value}"
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Mark as Paid", callback_data=f"cmd_markpaid_{o.order_id}")]
            ])
            await update.effective_message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)

@require_admin
async def markpaid_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manually mark an order as paid. Usage: /markpaid <order_id>"""
    if not context.args:
        await update.effective_message.reply_text(
            "❌ Usage: `/markpaid <order_id>`\n\nExample: `/markpaid ORD-12345`",
            parse_mode="Markdown"
        )
        return

    order_id = context.args[0].strip()
    async with async_session() as session:
        result = await session.execute(select(Order).where(Order.order_id == order_id))
        order = result.scalar_one_or_none()

        if not order:
            await update.effective_message.reply_text(f"❌ Order `{order_id}` not found.", parse_mode="Markdown")
            return

        if order.payment_status == PaymentStatusEnum.PAID:
            await update.effective_message.reply_text(f"ℹ️ Order `{order_id}` is already marked as PAID.", parse_mode="Markdown")
            return

        order.payment_status = PaymentStatusEnum.PAID
        session.add(Payment(sender_phone="manual", amount=float(order.price), matched_order_id=order.id))
        await session.commit()

        import asyncio
        asyncio.create_task(sheets.update_payment_status_in_sheets(order_id, "PAID"))

    await update.effective_message.reply_text(
        f"✅ *Order Marked as Paid*\n\nID: `{order_id}`\nProduct: {order.product_name}\nAmount: ৳{order.price}",
        parse_mode="Markdown",
        reply_markup=get_main_menu_keyboard()
    )

async def _send_sheets_check(update: Update, edit: bool = False):
    sheet_name = await config_service.get_active_sheet_name()
    sheet_url = await config_service.get_active_sheet_url()
    
    if not sheet_name:
        msg = (
            "❌ <b>No Spreadsheet Linked</b>\n\n"
            "To sync your orders to Google Sheets, you must first connect a spreadsheet in the settings."
        )
        keyboard = [[InlineKeyboardButton("⚙️ Go to Settings", callback_data="cmd_settings")]]
        keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data="cmd_main_menu")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        if edit and update.callback_query:
            await update.callback_query.edit_message_text(msg, parse_mode="HTML", reply_markup=reply_markup)
        else:
            await update.effective_message.reply_html(msg, reply_markup=reply_markup)
        return

    # If we already have the URL in DB, show it instantly
    if sheet_url:
        msg = (
            f"✅ <b>Connected to Google Sheets</b>\n"
            f"Sheet Name: <code>{sheet_name}</code>\n\n"
            f"Click the button below to open your spreadsheet."
        )
        keyboard = [[InlineKeyboardButton("📄 Open Sheet", url=sheet_url)]]
        keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data="cmd_main_menu")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        if edit and update.callback_query:
            await update.callback_query.edit_message_text(msg, parse_mode="HTML", reply_markup=reply_markup)
        else:
            await update.effective_message.reply_html(msg, reply_markup=reply_markup)
        return

    # Fallback to full check if URL is missing
    result = await sheets.check_google_sheets_connection(sheet_name)
    if result["success"]:
        final_url = result["url"]
        await config_service.set_active_sheet_url(final_url)
        msg = (
            f"✅ <b>Connected to Google Sheets</b>\n"
            f"Sheet Name: <code>{sheet_name}</code>\n\n"
            "Click the button below to open your spreadsheet.\n\n"
            "<i>💡 Tip: Make sure you've also shared this sheet with your personal Google email for access.</i>"
        )
        keyboard = [[InlineKeyboardButton("📄 Open Sheet", url=final_url)]]
        keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data="cmd_main_menu")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        if edit and update.callback_query:
            await update.callback_query.edit_message_text(msg, parse_mode="HTML", reply_markup=reply_markup)
        else:
            await update.effective_message.reply_html(msg, reply_markup=reply_markup)
    else:
        msg = f"❌ <b>Link Broken</b>: {result['error']}\n\nPlease check the name in <b>Settings</b>."
        keyboard = [[InlineKeyboardButton("⚙️ Manage Spreadsheet", callback_data="cmd_manage_sheets")]]
        keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data="cmd_main_menu")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        if edit and update.callback_query:
            await update.callback_query.edit_message_text(msg, parse_mode="HTML", reply_markup=reply_markup)
        else:
            await update.effective_message.reply_html(msg, reply_markup=reply_markup)

@require_admin
async def check_sheets_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_sheets_check(update, edit=False)

@require_admin
async def forcereport_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin-only: manually trigger daily/weekly/monthly report for testing.
    Usage: /forcereport daily | /forcereport weekly | /forcereport monthly
    """
    from src.scheduler.report_scheduler import _generate_daily_report, _generate_weekly_report, _generate_monthly_report

    args = context.args
    report_type = args[0].lower() if args else "daily"

    if report_type == "weekly":
        await update.effective_message.reply_text("⏳ Sending weekly report now...")
        await _generate_weekly_report()
    elif report_type == "monthly":
        await update.effective_message.reply_text("⏳ Sending monthly report now...")
        await _generate_monthly_report()
    else:
        await update.effective_message.reply_text("⏳ Sending daily report now...")
        await _generate_daily_report()

    await update.effective_message.reply_text("✅ Report sent!", reply_markup=get_main_menu_keyboard())


@require_moderator_or_admin
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    logger.info(f"Button clicked: {query.data}")
    
    user_id = str(query.from_user.id)
    from src.auth.roles import get_user_role, RoleEnum
    role = await get_user_role(user_id)
    
    # List of commands that are strictly for Admins only
    admin_only_prefixes = [
        "cmd_today_", "cmd_orders_", "cmd_top", "cmd_pending",
        "cmd_weekly", "cmd_monthly", "cmd_growth", "cmd_alerts",
        "cmd_check_sheets", "cmd_settings", "cmd_generate_invite",
        "cmd_gen_invite_", "cmd_list_mods", "cmd_manage_bans",
        "cmd_prompt_", "cmd_admin_mgmt", "cmd_gen_admin_invite",
        "cmd_remove_admin_", "cmd_manage_sheets",
        "cmd_sched", "cmd_sa_",
    ]
    
    is_admin_cmd = False
    for prefix in admin_only_prefixes:
        if query.data.startswith(prefix):
            is_admin_cmd = True
            break
            
    if is_admin_cmd and role not in ADMIN_ROLES:
        await query.answer("⛔ Access Denied. Admin privileges required.", show_alert=True)
        return

    # Check for spreadsheet requirement on specific feature buttons
    feature_commands = [
        "cmd_today_", "cmd_orders_", "cmd_top", "cmd_pending",
        "cmd_weekly", "cmd_monthly", "cmd_growth", "cmd_alerts",
        "cmd_stock", "cmd_team_stats", "cmd_mod_stock", "cmd_my_stats"
    ]
    if any(query.data.startswith(c) for c in feature_commands):
        sheet_name = await config_service.get_active_sheet_name()
        if not sheet_name:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            if role in ADMIN_ROLES:
                msg = (
                    "📊 **Spreadsheet Required**\n\n"
                    "Before you can use any tracking features, you must connect a Google Spreadsheet.\n\n"
                    "Tap the button below to start the connection guide:"
                )
                keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Connect Spreadsheet", callback_data="cmd_manage_sheets")]])
            else:
                msg = (
                    "⚠️ **System Not Ready**\n\n"
                    "Your Admin has not connected a Google Spreadsheet yet. "
                    "Features will be enabled once the setup is complete."
                )
                keyboard = None
            
            await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=keyboard)
            return

    if query.data == "cmd_sa_list_clients":
        await list_clients_command(update, context)
    elif query.data == "cmd_sa_add_client":
        context.user_data["awaiting_sa_client_name"] = True
        msg = (
            "➕ *Add a New Client*\n\n"
            "This wizard will guide you through creating a new client.\n\n"
            "*Step 1 of 3:*\n"
            "Please send the *Name* of the new client (e.g. `Lux Corporation`):"
        )
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cmd_main_menu")]])
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=keyboard)
    elif query.data == "cmd_sa_confirm_client":
        client_name = context.user_data.get("sa_new_client_name")
        bot_token = context.user_data.get("sa_new_client_token")
        sheet_name = context.user_data.get("sa_new_client_sheet")
        
        if not client_name or not bot_token:
            await query.answer("Missing data. Please try adding again.", show_alert=True)
            return
            
        await query.edit_message_text("⏳ Creating workspace and starting bot. Please wait...", parse_mode="Markdown")
        
        try:
            tenant = await tenant_service.create_tenant(client_name, bot_token, sheet_name)
        except ValueError as exc:
            await query.edit_message_text(f"❌ {exc}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Menu", callback_data="cmd_main_menu")]]))
            return

        admin_code = await generate_admin_invite_code(str(tenant.id))
        app = await bot_manager.start_tenant_bot(tenant)
        bot_username = bot_manager.get_bot_username(str(tenant.id))
        invite_link = _build_invite_link(bot_username, admin_code) if admin_code else None

        status_line = "✅ Bot started successfully." if app else "⚠️ Client saved, but the bot could not be started. Please verify the token."
        bot_line = f"@{bot_username}" if bot_username else "_Username unavailable until the bot starts successfully_"

        lines = [
            f"✅ *Client Created:* {tenant.name}",
            f"Client ID: `{tenant.id}`",
            f"Bot: {bot_line}",
            status_line,
        ]
        if tenant.google_sheet_name:
            lines.append(f"Sheet: `{tenant.google_sheet_name}`")
        if admin_code:
            lines.append("")
            lines.append("*Client Admin Access*")
            if invite_link:
                lines.append(invite_link)
            lines.append(f"Fallback code: `/join {admin_code}`")
            
        await query.edit_message_text("\n".join(lines), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Menu", callback_data="cmd_main_menu")]]))

    if query.data == "cmd_today_all":
        await _send_today_sales(update, platform=None)
    elif query.data == "cmd_today_FACEBOOK":
        await _send_today_sales(update, platform=PlatformEnum.FACEBOOK)
    elif query.data == "cmd_today_WHATSAPP":
        await _send_today_sales(update, platform=PlatformEnum.WHATSAPP)
    elif query.data.startswith("cmd_orders_"):
        # Handles both legacy (cmd_orders_all) and paginated (cmd_orders_all_10) formats
        parts = query.data.split("_")
        if len(parts) >= 4 and parts[-1].isdigit():
            page_offset = int(parts[-1])
            plat_key = "_".join(parts[2:-1])
        else:
            page_offset = 0
            plat_key = "_".join(parts[2:])
        if plat_key == "FACEBOOK":
            plat = PlatformEnum.FACEBOOK
        elif plat_key == "WHATSAPP":
            plat = PlatformEnum.WHATSAPP
        else:
            plat = None
        await _send_recent_orders(update, platform=plat, edit=True, offset=page_offset)
    elif query.data == "cmd_top":
        await top_command(update, context)
    elif query.data == "cmd_pending":
        await pending_command(update, context)
    elif query.data == "cmd_stock":
        await stock_command(update, context)
    elif query.data == "cmd_team_stats":
        await team_stats_command(update, context)
    elif query.data == "cmd_weekly":
        await weekly_command(update, context)
    elif query.data == "cmd_monthly":
        await monthly_command(update, context)
    elif query.data == "cmd_growth":
        await growth_command(update, context)
    elif query.data == "cmd_alerts":
        await alerts_command(update, context)
    elif query.data == "cmd_check_sheets":
        await _send_sheets_check(update, edit=True)
    elif query.data == "cmd_settings":
        await query.edit_message_text("⚙️ **Settings & Management**\n\nChoose an option:", parse_mode="Markdown", reply_markup=get_settings_keyboard())

    # ── Schedule & Alert Settings ──────────────────────────────────────────
    elif query.data == "cmd_schedule_menu":
        text, keyboard = await _build_schedule_overview()
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)

    elif query.data.startswith("cmd_sched_job_"):
        job_id = query.data[len("cmd_sched_job_"):]
        if job_id not in SCHEDULE_JOBS:
            await query.answer("Unknown job.", show_alert=True)
            return
        text, keyboard = await _build_job_detail(job_id)
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)

    elif query.data.startswith("cmd_sched_settime_"):
        job_id = query.data[len("cmd_sched_settime_"):]
        if job_id not in SCHEDULE_JOBS:
            await query.answer("Unknown job.", show_alert=True)
            return
        cfg = SCHEDULE_JOBS[job_id]
        current_t = await config_service.get_job_time(job_id)
        context.user_data["awaiting_schedule_time_for"] = job_id
        text = (
            f"⏰ *Set Time — {cfg['name']}*\n"
            f"_{cfg['description']}_\n"
            f"\n"
            f"Current time: `{current_t}` (Dhaka / GMT+6)\n"
            f"\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"*Instructions:*\n"
            f"Send the new time in *24-hour HH:MM* format.\n"
            f"\n"
            f"*Valid examples:*\n"
            f"  `06:00`  →  6:00 AM\n"
            f"  `12:00`  →  12:00 PM (Noon)\n"
            f"  `18:30`  →  6:30 PM\n"
            f"  `23:59`  →  11:59 PM\n"
            f"\n"
            f"_Hours must be 00–23, minutes 00–59._"
        )
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Cancel", callback_data=f"cmd_sched_job_{job_id}")
        ]])
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)

    elif query.data.startswith("cmd_sched_toggle_"):
        job_id = query.data[len("cmd_sched_toggle_"):]
        if job_id not in SCHEDULE_JOBS:
            await query.answer("Unknown job.", show_alert=True)
            return
        from src.scheduler.report_scheduler import toggle_job_enabled
        new_state = await toggle_job_enabled(job_id)
        if new_state is None:
            await query.answer("This alert cannot be toggled.", show_alert=True)
            return
        cfg = SCHEDULE_JOBS[job_id]
        status_word = "enabled ✅" if new_state else "disabled 🔴"
        await query.answer(f"{cfg['name']} {status_word}", show_alert=False)
        # Refresh the job detail card
        text, keyboard = await _build_job_detail(job_id)
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)
    # ── End Schedule & Alert Settings ─────────────────────────────────────

    elif query.data == "cmd_generate_invite":
        await generate_invite_command(update, context)
    elif query.data == "cmd_gen_invite_FACEBOOK":
        await _do_generate_invite(update, context, PlatformEnum.FACEBOOK)
    elif query.data == "cmd_gen_invite_WHATSAPP":
        await _do_generate_invite(update, context, PlatformEnum.WHATSAPP)
    elif query.data == "cmd_list_mods":
        await list_mod_command(update, context)
    elif query.data == "cmd_manage_bans":
        text = "⚙️ **Manage Bans:**\nWhat would you like to do?"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Ban Moderator", callback_data="cmd_prompt_ban")],
            [InlineKeyboardButton("♻️ Unban Moderator", callback_data="cmd_prompt_unban")],
            [InlineKeyboardButton("🔙 Back to List", callback_data="cmd_list_mods")]
        ])
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)
    elif query.data == "cmd_prompt_ban":
        mods = await get_all_moderators()
        active_mods = [m for m in mods if not m['is_banned']]
        
        text = "❌ **Ban a Moderator**\n\nTo ban a user, copy their ID from the list below and send: `/ban ID`\n\n**Active Moderators:**\n"
        if not active_mods:
            text += "*(No active moderators available)*"
        else:
            for idx, m in enumerate(active_mods, 1):
                text += f"{idx}. {m['name']} — `{m['id']}`\n"
                
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="cmd_manage_bans")]])
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)
        
    elif query.data == "cmd_prompt_unban":
        mods = await get_all_moderators()
        banned_mods = [m for m in mods if m['is_banned']]
        
        text = "♻️ **Unban a Moderator**\n\nTo unban a user, copy their ID from the list below and send: `/unban ID`\n\n**Banned Moderators:**\n"
        if not banned_mods:
            text += "*(No banned moderators)*"
        else:
            for idx, m in enumerate(banned_mods, 1):
                text += f"{idx}. {m['name']} — `{m['id']}`\n"
                
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="cmd_manage_bans")]])
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)
    elif query.data == "cmd_my_stats":
        await moderator_stats_command(update, context)

    # --- Admin: Update Stock from low stock alert button ---
    elif query.data.startswith("cmd_admin_setstock_"):
        if role not in ADMIN_ROLES:
            await query.answer("⛔ Only admins can update stock.", show_alert=True)
            return
        product_name = query.data.replace("cmd_admin_setstock_", "")
        from src.db.models import Product as _Product
        async with async_session() as session:
            res = await session.execute(select(_Product).where(_Product.name == product_name))
            prod = res.scalar_one_or_none()
        current_stock = prod.current_stock if prod else "not tracked"
        context.user_data["awaiting_setstock_product"] = product_name
        await query.edit_message_text(
            f"📦 *Update Stock for:* `{product_name}`\n"
            f"📊 Current stock: *{current_stock}*\n\n"
            f"Send the new stock quantity:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cmd_main_menu")]])
        )

    # --- Moderator: Check Stock ---
    elif query.data == "cmd_mod_stock":
        await mod_stock_command(update, context)

    # --- Moderator: Search My Orders prompt ---
    elif query.data == "cmd_mod_search_prompt":
        context.user_data["awaiting_mod_search"] = True
        await query.edit_message_text(
            "🔍 *Search My Orders*\n\nType your search term and send it:\n\n"
            "• Product name  (e.g. `Nike`)\n"
            "• Phone number  (e.g. `01712`)\n"
            "• Order ID      (e.g. `ORD-225`)",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cmd_main_menu")]])
        )

    # --- Moderator: Report Low Stock prompt ---
    elif query.data == "cmd_mod_lowstock_prompt":
        context.user_data["awaiting_mod_lowstock_name"] = True
        await query.edit_message_text(
            "⚠️ *Report Low Stock — Step 1 of 2*\n\nType the *product name*:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cmd_main_menu")]])
        )

    # --- Moderator: Low stock — confirmed suggested product ---
    elif query.data.startswith("cmd_lowstock_pick_"):
        product_name = query.data[len("cmd_lowstock_pick_"):]
        from src.db.models import Product as _Product
        async with async_session() as session:
            res = await session.execute(select(_Product).where(_Product.name == product_name))
            prod = res.scalar_one_or_none()
        stock_info = f"📊 Current stock: *{prod.current_stock}*" if prod else "📊 _(not tracked)_"
        context.user_data["awaiting_mod_lowstock_msg"] = product_name
        await query.edit_message_text(
            f"✅ Product: *{product_name}*\n{stock_info}\n\n"
            f"⚠️ *Step 2 of 2* — Describe the issue\n_(e.g. 'Almost finished, need restock soon')_:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cmd_main_menu")]])
        )

    # --- Moderator: Low stock — report unrecognised product anyway ---
    elif query.data.startswith("cmd_lowstock_anyway_"):
        product_name = query.data[len("cmd_lowstock_anyway_"):]
        context.user_data["awaiting_mod_lowstock_msg"] = product_name
        await query.edit_message_text(
            f"⚠️ *Step 2 of 2* — Describe the issue for *{product_name}*\n_(e.g. 'Almost finished, need restock soon')_:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cmd_main_menu")]])
        )

    elif query.data == "cmd_main_menu":
        context.user_data.pop("awaiting_sa_client_name", None)
        context.user_data.pop("awaiting_sa_bot_token", None)
        context.user_data.pop("awaiting_sa_sheet_id", None)
        
        user_id = str(query.from_user.id)
        role = await get_user_role(user_id)
        if role == RoleEnum.SUPERADMIN:
            await query.edit_message_text(
                "Welcome back, Owner!\n\nThis is the Superadmin control panel. You can manage your clients, active bots, and platform configuration here.",
                parse_mode="Markdown",
                reply_markup=get_superadmin_menu_keyboard()
            )
        elif role in ADMIN_ROLES:
            sheet_name = await config_service.get_active_sheet_name()
            if not sheet_name:
                await _send_spreadsheet_setup_needed(update, role)
                return
            await query.edit_message_text("Welcome to the Multi-Platform Order Tracking Agent 🤖\n\nPlease select an option below:", reply_markup=get_main_menu_keyboard())
        else:
            await query.edit_message_text("Welcome back! Use the keyboard below to check your stats or just send an #ORDER.")

    elif query.data == "cmd_admin_mgmt":
        if str(query.from_user.id) != str(settings.TELEGRAM_CHAT_ID):
            await query.answer("⛔ Only the primary admin can manage admin access.", show_alert=True)
            return
        secondary = await get_tenant_admin(get_tenant_id())
        if secondary:
            text = (
                f"👑 *Admin Management*\n\n"
                f"Current Secondary Admin:\n"
                f"👤 *{secondary['name']}*\n"
                f"ID: `{secondary['id']}`\n\n"
                f"You can remove them if needed."
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🗑️ Remove Secondary Admin", callback_data=f"cmd_remove_admin_{secondary['id']}")],
                [InlineKeyboardButton("🔙 Back to Settings", callback_data="cmd_settings")]
            ])
        else:
            text = (
                "👑 *Admin Management*\n\n"
                "No secondary admin assigned yet.\n\n"
                "You can invite one trusted person to have full admin access.\n"
                "_(Only 1 secondary admin is allowed at a time)_"
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Generate Admin Invite", callback_data="cmd_gen_admin_invite")],
                [InlineKeyboardButton("🔙 Back to Settings", callback_data="cmd_settings")]
            ])
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)

    elif query.data == "cmd_gen_admin_invite":
        code = await generate_admin_invite_code(get_tenant_id())
        if code is None:
            await query.answer("⚠️ A secondary admin already exists. Remove them first.", show_alert=True)
        else:
            bot_username = getattr(context.bot, "username", None)
            invite_link = _build_invite_link(bot_username, code)
            forward_msg = (
                f"👑 *You have been invited as an Admin!*\n\n"
                f"{invite_link + chr(10) + chr(10) if invite_link else ''}"
                f"Open the bot @{bot_username} and send:\n"
                f"`/join {code}`\n\n"
                f"This code can only be used once."
            )
            await query.edit_message_text(
                f"✅ *Admin Invite Generated!*\n\nForward the message below to your new admin:",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="cmd_admin_mgmt")]])
            )
            await query.message.reply_text(forward_msg, parse_mode="Markdown")

    elif query.data.startswith("cmd_remove_admin_"):
        admin_id = query.data.replace("cmd_remove_admin_", "")
        success = await remove_tenant_admin(admin_id, get_tenant_id())
        if success:
            await query.edit_message_text(
                "✅ *Secondary admin removed successfully.*",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Settings", callback_data="cmd_settings")]])
            )
        else:
            await query.answer("❌ Could not remove admin.", show_alert=True)

    elif query.data == "cmd_manage_sheets":
        sheet_name = await config_service.get_active_sheet_name()
        status = f"🟢 Connected to: `{sheet_name}`" if sheet_name else "🔴 *Not Connected*"
        email = await _get_service_account_email()

        text = (
            "📊 **Manage Spreadsheet Connection**\n\n"
            f"**Status:** {status}\n\n"
            "📌 **How to connect a new Spreadsheet:**\n"
            "1️⃣ **Create:** Open Google Sheets and create a new blank spreadsheet.\n"
            "2️⃣ **Share:** Click the blue *Share* button in the top right corner.\n"
            "3️⃣ **Add Bot:** Paste this exact email address and give it **Editor** access:\n"
            f"`{email}`\n"
            "4️⃣ **Link:** Tap the *🔗 Set/Change Connection* button below.\n"
            "5️⃣ **Submit:** The bot will ask for the URL. Simply copy the link to your spreadsheet from your browser and send it to the bot.\n"
        )
        buttons = [
            [InlineKeyboardButton("🔗 Set/Change Connection", callback_data="cmd_prompt_sheet_name")]
        ]
        if sheet_name:
            buttons.append([InlineKeyboardButton("❌ Disconnect Spreadsheet", callback_data="cmd_disconnect_sheets")])
        buttons.append([InlineKeyboardButton("🔙 Back to Settings", callback_data="cmd_settings")])
        
        keyboard = InlineKeyboardMarkup(buttons)
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)

    elif query.data == "cmd_disconnect_sheets":
        await config_service.set_active_sheet_name(None)
        await config_service.set_active_sheet_url(None)
        await query.edit_message_text(
            "✅ **Spreadsheet Disconnected**\n\nThe bot will no longer sync orders to Google Sheets.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Settings", callback_data="cmd_settings")]])
        )

    elif query.data == "cmd_prompt_sheet_name":
        context.user_data["awaiting_sheet_name"] = True

        # Resolve service-account email for the reminder
        import json as _json
        try:
            if settings.GSHEETS_CONFIG_JSON:
                _creds = _json.loads(settings.GSHEETS_CONFIG_JSON)
            else:
                with open("service_account.json", "r") as _f:
                    _creds = _json.load(_f)
            sa_email = _creds.get("client_email", "_(email not found)_")
        except Exception:
            sa_email = "_(could not read credentials)_"

        text = (
            "📝 **Send the Google Spreadsheet URL**\n\n"
            "Please paste the full link (URL) of your Google Spreadsheet here. "
            "You can also send just the Spreadsheet ID if you prefer.\n\n"
            f"⚠️ *Reminder:* Make sure this email has been added as an *Editor* in your spreadsheet's Share settings:\n`{sa_email}`"
        )
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cmd_manage_sheets")]])
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)

    elif query.data.startswith("cmd_markpaid_"):
        order_id = query.data.replace("cmd_markpaid_", "")
        price = None

        async with async_session() as session:
            result = await session.execute(select(Order).where(Order.order_id == order_id))
            order = result.scalar_one_or_none()

            if not order:
                await query.answer("❌ Order not found.", show_alert=True)
                return

            # Moderators can only mark their own orders as paid
            if role not in ADMIN_ROLES and order.created_by_id != user_id:
                await query.answer("⛔ You can only mark your own orders as paid.", show_alert=True)
                return

            if order.payment_status == PaymentStatusEnum.PAID:
                await query.answer("ℹ️ Already marked as PAID.", show_alert=True)
                return

            price = float(order.price)

            order.payment_status = PaymentStatusEnum.PAID
            session.add(Payment(sender_phone="manual", amount=price, matched_order_id=order.id))
            await session.commit()
            await session.refresh(order)

            import asyncio
            asyncio.create_task(sheets.update_payment_status_in_sheets(order_id, "PAID"))

            card = _order_card_text(order)

        await query.edit_message_text(
            f"✅ *Marked as Paid!*\n\n{card}",
            parse_mode="Markdown",
            reply_markup=_order_action_keyboard(order_id)
        )

    # --- Search prompt (from main menu button) ---
    elif query.data == "cmd_search_prompt":
        context.user_data["awaiting_search"] = True
        await query.edit_message_text(
            "🔍 *Order Search*\n\nType your search term and send it:\n\n"
            "• Product name  (e.g. `Nike`)\n"
            "• Phone number  (e.g. `01712`)\n"
            "• Order ID      (e.g. `ORD-225`)",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cmd_main_menu")]])
        )

    # --- Edit order: show field selection ---
    elif query.data.startswith("cmd_edit_"):
        order_id = query.data.replace("cmd_edit_", "")
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📦 Product", callback_data=f"cmd_ef_{order_id}_product"),
                InlineKeyboardButton("🔢 Qty",     callback_data=f"cmd_ef_{order_id}_qty"),
            ],
            [
                InlineKeyboardButton("💰 Price",   callback_data=f"cmd_ef_{order_id}_price"),
                InlineKeyboardButton("📱 Phone",   callback_data=f"cmd_ef_{order_id}_phone"),
            ],
            [InlineKeyboardButton("✅ Status → PAID", callback_data=f"cmd_ef_{order_id}_markpaid")],
            [InlineKeyboardButton("↩️ Back to Order", callback_data=f"cmd_view_order_{order_id}")]
        ])
        await query.edit_message_text(
            f"✏️ *Edit Order `{order_id}`*\n\nWhich field do you want to change?",
            parse_mode="Markdown", reply_markup=keyboard
        )

    # --- Edit order: capture field, ask for new value ---
    elif query.data.startswith("cmd_ef_"):
        raw = query.data[len("cmd_ef_"):]          # e.g. "ORD-225_price"
        field = raw.rsplit("_", 1)[-1]              # last segment = field
        order_id = raw[: -(len(field) + 1)]         # everything before last _<field>

        if field == "markpaid":
            async with async_session() as session:
                result = await session.execute(select(Order).where(Order.order_id == order_id))
                order = result.scalar_one_or_none()
                if order and order.payment_status != PaymentStatusEnum.PAID:
                    order.payment_status = PaymentStatusEnum.PAID
                    session.add(Payment(sender_phone="manual", amount=float(order.price), matched_order_id=order.id))
                    await session.commit()
                    await session.refresh(order)
                if order:
                    card = _order_card_text(order)
                    import asyncio
                    asyncio.create_task(sheets.update_payment_status_in_sheets(order_id, "PAID"))
                else:
                    card = f"Order `{order_id}` not found."
            await query.edit_message_text(
                f"✅ *Marked as Paid!*\n\n{card}",
                parse_mode="Markdown",
                reply_markup=_order_action_keyboard(order_id)
            )
            return

        field_labels = {"product": "product name", "qty": "quantity", "price": "price", "phone": "phone number"}

        # Fetch current value to show in the prompt
        async with async_session() as session:
            result = await session.execute(select(Order).where(Order.order_id == order_id))
            order = result.scalar_one_or_none()

        current_values = {
            "product": order.product_name if order else "—",
            "qty":     str(order.quantity) if order else "—",
            "price":   str(int(order.price)) if order else "—",
            "phone":   order.phone_number or "—" if order else "—",
        }
        current_labels = {
            "product": "Current product",
            "qty":     "Current quantity",
            "price":   "Current price",
            "phone":   "Current phone",
        }
        current = current_values.get(field, "—")
        current_label = current_labels.get(field, "Current value")

        context.user_data["editing_order_id"] = order_id
        context.user_data["editing_field"] = field
        await query.edit_message_text(
            f"✏️ *Edit `{field_labels.get(field, field)}` for order `{order_id}`*\n\n"
            f"{current_label}: `{current}`\n\n"
            f"Send the new value now:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel Edit", callback_data=f"cmd_view_order_{order_id}")]])
        )

    # --- View order card (used by Cancel Edit to restore the order) ---
    elif query.data.startswith("cmd_view_order_"):
        order_id = query.data.replace("cmd_view_order_", "")
        # Clear any stale edit state
        context.user_data.pop("editing_order_id", None)
        context.user_data.pop("editing_field", None)
        async with async_session() as session:
            result = await session.execute(select(Order).where(Order.order_id == order_id))
            order = result.scalar_one_or_none()
        if not order:
            await query.edit_message_text(f"❌ Order `{order_id}` not found.", parse_mode="Markdown")
        else:
            await query.edit_message_text(
                _order_card_text(order),
                parse_mode="Markdown",
                reply_markup=_order_action_keyboard(order_id)
            )

    # --- Cancel order: confirm step ---
    elif query.data.startswith("cmd_cancel_"):
        order_id = query.data.replace("cmd_cancel_", "")
        async with async_session() as session:
            result = await session.execute(select(Order).where(Order.order_id == order_id))
            order = result.scalar_one_or_none()
            if not order:
                await query.answer("❌ Order not found.", show_alert=True)
                return
            if order.payment_status == PaymentStatusEnum.PAID:
                await query.answer("⛔ You cannot cancel a paid order.", show_alert=True)
                return

        await query.edit_message_text(
            f"⚠️ *Cancel Order `{order_id}`?*\n\nThis will mark the order as cancelled and restore its stock.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🚫 Yes, Cancel It", callback_data=f"cmd_confirmcancel_{order_id}")],
                [InlineKeyboardButton("↩️ No, Keep It",   callback_data="cmd_main_menu")]
            ])
        )

    # --- Cancel order: confirmed, cancel ---
    elif query.data.startswith("cmd_confirmcancel_"):
        order_id = query.data.replace("cmd_confirmcancel_", "")
        async with async_session() as session:
            result = await session.execute(select(Order).where(Order.order_id == order_id))
            order = result.scalar_one_or_none()
            if not order:
                await query.answer("❌ Order not found.", show_alert=True)
                return
            if order.payment_status == PaymentStatusEnum.PAID:
                await query.answer("⛔ You cannot cancel a paid order.", show_alert=True)
                return
            
            # Stock reversal
            from src.db.models import Product
            prod_res = await session.execute(select(Product).where(Product.name == order.product_name))
            prod = prod_res.scalar_one_or_none()
            # If product exists and stock was being tracked (or if we want to just add it back anyway, but let's just add it back if we can)
            if prod:
                prod.current_stock += order.quantity

            order.payment_status = PaymentStatusEnum.CANCELLED
            await session.commit()
            
        import asyncio as _asyncio
        _asyncio.create_task(sheets.update_payment_status_in_sheets(order_id, "CANCELLED"))
        
        await query.edit_message_text(
            f"🗑️ Order `{order_id}` has been cancelled and stock returned.",
            parse_mode="Markdown"
        )


# --- Order Processing (Moderator & Admin) ---

@require_moderator_or_admin
@require_spreadsheet
async def mod_stock_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show available product stock for moderators (read-only, no business metrics)."""
    async with async_session() as session:
        products = await analytics.get_all_products(session)

    if not products:
        msg = (
            "📦 *Stock Status*\n\n"
            "No products tracked yet.\n"
            "Products appear here automatically after orders are submitted."
        )
    else:
        lines = ["📦 *Stock Status*\n"]
        for p in products:
            if p.current_stock == 0:
                icon, status = "🔴", "Out of stock"
            elif p.current_stock <= 10:
                icon, status = "🟡", f"Low — {p.current_stock} left"
            else:
                icon, status = "🟢", f"{p.current_stock} available"
            lines.append(f"{icon} *{p.name}* — {status}")
        msg = "\n".join(lines)

    if update.callback_query:
        await update.callback_query.edit_message_text(msg, parse_mode="Markdown")
    else:
        await update.effective_message.reply_text(msg, parse_mode="Markdown")


async def _send_lowstock_alert(product_name: str, reporter_name: str, description: str = "") -> None:
    """Sends a low stock alert to all admins with current stock and an Update Stock button."""
    from src.services.notifier import send_admin_alert
    from src.db.models import Product

    # Fetch current stock for this product
    async with async_session() as session:
        result = await session.execute(select(Product).where(Product.name == product_name))
        product = result.scalar_one_or_none()

    current_stock = product.current_stock if product else None
    stock_line = f"📊 Current stock: *{current_stock}*" if current_stock is not None else "📊 Current stock: _not tracked_"

    desc_line = f"💬 _{description}_\n" if description else ""

    # Callback data limited to 64 bytes — use product name only (not description)
    cb_product = product_name[:42]
    markup = {
        "inline_keyboard": [[
            {"text": "📦 Update Stock", "callback_data": f"cmd_admin_setstock_{cb_product}"}
        ]]
    }

    await send_admin_alert(
        f"⚠️ *Low Stock Report*\n\n"
        f"👤 *{reporter_name}* reported:\n"
        f"📦 *{product_name}*\n"
        f"{desc_line}"
        f"{stock_line}\n\n"
        f"Tap the button below to update stock.",
        reply_markup=markup
    )


@require_moderator_or_admin
@require_spreadsheet
async def lowstock_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Moderator reports a low stock product to admin. Usage: /lowstock <product name>"""
    if not context.args:
        await update.effective_message.reply_text(
            "⚠️ Usage: `/lowstock <product name>`\n\nExample: `/lowstock Nike Air Max`",
            parse_mode="Markdown"
        )
        return

    product_name = " ".join(context.args).strip().title()
    reporter_name = update.effective_user.full_name or "A moderator"
    await _send_lowstock_alert(product_name, reporter_name)
    await update.effective_message.reply_text(
        f"✅ Admin has been notified about low stock for *{product_name}*.",
        parse_mode="Markdown"
    )


@require_moderator_or_admin
@require_spreadsheet
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Processes incoming text messages for orders."""
    text = update.effective_message.text

    if context.user_data.get("awaiting_sa_client_name"):
        context.user_data["sa_new_client_name"] = text.strip()
        context.user_data["awaiting_sa_client_name"] = False
        context.user_data["awaiting_sa_bot_token"] = True
        await update.effective_message.reply_text(
            "✅ Name saved.\n\n"
            "*Step 2 of 3:*\n"
            "Please send the **Telegram Bot Token** for this new client\n_(get this from @BotFather)_:", 
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cmd_main_menu")]])
        )
        return

    if context.user_data.get("awaiting_sa_bot_token"):
        context.user_data["sa_new_client_token"] = text.strip()
        context.user_data["awaiting_sa_bot_token"] = False
        context.user_data["awaiting_sa_sheet_id"] = True

        # Resolve service-account email — same two-path logic as cmd_manage_sheets
        import json as _json
        try:
            if settings.GSHEETS_CONFIG_JSON:
                _creds = _json.loads(settings.GSHEETS_CONFIG_JSON)
            else:
                with open("service_account.json", "r") as _f:
                    _creds = _json.load(_f)
            sa_email = _creds.get("client_email", "_(email not found)_")
        except Exception:
            sa_email = "_(could not read credentials)_"

        await update.effective_message.reply_text(
            "✅ Token saved.\n\n"
            "*Step 3 of 3 — Link a Google Spreadsheet* 📊\n\n"
            "You can link a Google Spreadsheet so that every order placed through this client's bot is automatically synced there.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "*How to set it up:*\n"
            "1️⃣ Open Google Sheets and create a new blank spreadsheet.\n"
            "2️⃣ Click the blue *Share* button (top-right corner).\n"
            f"3️⃣ Paste this exact email and give it *Editor* access:\n`{sa_email}`\n"
            "4️⃣ Copy the spreadsheet URL from your browser and paste it here.\n\n"
            "💡 *You can also paste just the Spreadsheet ID* — the long string between `/d/` and `/edit` in the URL.\n\n"
            "*(If you don't want to link one right now, type `skip`)*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cmd_main_menu")]])
        )
        return

    if context.user_data.get("awaiting_sa_sheet_id"):
        sheet_input = text.strip()
        if sheet_input.lower() == "skip":
            sheet_input = None
        context.user_data["sa_new_client_sheet"] = sheet_input
        context.user_data["awaiting_sa_sheet_id"] = False
        
        name = context.user_data["sa_new_client_name"]
        token = context.user_data["sa_new_client_token"]
        sheet = context.user_data["sa_new_client_sheet"]
        
        msg = (
            "📝 **Confirm New Client Details**\n\n"
            f"**Name:** {name}\n"
            f"**Token:** `{token}`\n"
            f"**Sheet:** {sheet or 'None'}\n\n"
            "Does everything look correct?"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Confirm & Create", callback_data="cmd_sa_confirm_client")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cmd_main_menu")]
        ])
        await update.effective_message.reply_text(msg, parse_mode="Markdown", reply_markup=keyboard)
        return

    # Handle persistent keyboard "Main Menu" button tap
    if text and text.strip() == "🏠 Main Menu":
        user_id = str(update.effective_user.id)
        role = await get_user_role(user_id)
        if role in ADMIN_ROLES:
            await update.effective_message.reply_text("📌 Quick access menu updated.", reply_markup=get_persistent_keyboard())
            await update.effective_message.reply_text(
                "Welcome to the Multi-Platform Order Tracking Agent 🤖\n\nPlease select an option below:",
                reply_markup=get_main_menu_keyboard()
            )
        else:
            await update.effective_message.reply_text(
                "Welcome back! Use the keyboard below or send an #ORDER.",
                reply_markup=get_moderator_persistent_keyboard()
            )
        return

    # Handle persistent keyboard "My Stats Today" button tap (Moderator)
    if text and text.strip() == "📊 My Stats Today":
        await moderator_stats_command(update, context)
        return

    # Handle persistent keyboard "Check Stock" button tap (Moderator)
    if text and text.strip() == "📦 Check Stock":
        await mod_stock_command(update, context)
        return

    # Handle persistent keyboard "Search My Orders" button tap (Moderator)
    if text and text.strip() == "🔍 Search My Orders":
        context.user_data["awaiting_mod_search"] = True
        await update.effective_message.reply_text(
            "🔍 *Search My Orders*\n\nType your search term and send it:\n\n"
            "• Product name  (e.g. `Nike`)\n"
            "• Phone number  (e.g. `01712`)\n"
            "• Order ID      (e.g. `ORD-225`)",
            parse_mode="Markdown"
        )
        return

    # Handle persistent keyboard "Report Low Stock" button tap (Moderator)
    if text and text.strip() == "⚠️ Report Low Stock":
        context.user_data["awaiting_mod_lowstock_name"] = True
        await update.effective_message.reply_text(
            "⚠️ *Report Low Stock — Step 1 of 2*\n\nType the *exact product name*:",
            parse_mode="Markdown"
        )
        return

    # Handle persistent keyboard "Today's Sales" button tap (Admin)
    if text and text.strip() == "📊 Today's Sales":
        user_id = str(update.effective_user.id)
        role = await get_user_role(user_id)
        if role in ADMIN_ROLES:
            await today_command(update, context)
        return

    if not text or not text.strip().upper().startswith("#ORDER"):
        user_id = str(update.effective_user.id)
        role = await get_user_role(user_id)

        # --- Handle awaiting edit value (both Admin and Moderator) ---
        if context.user_data.get("editing_order_id"):
            order_id = context.user_data.pop("editing_order_id")
            field    = context.user_data.pop("editing_field")
            new_val  = text.strip()

            async with async_session() as session:
                result = await session.execute(select(Order).where(Order.order_id == order_id))
                order = result.scalar_one_or_none()
                if not order:
                    await update.effective_message.reply_text(f"❌ Order `{order_id}` not found.", parse_mode="Markdown")
                    return
                # Moderators can only edit their own orders
                if role not in ADMIN_ROLES and order.created_by_id != user_id:
                    await update.effective_message.reply_text("⛔ You can only edit your own orders.", parse_mode="Markdown")
                    return
                try:
                    if field == "product":
                        order.product_name = new_val.title()
                    elif field == "qty":
                        order.quantity = int(new_val)
                    elif field == "price":
                        order.price = float(new_val)
                    elif field == "phone":
                        order.phone_number = new_val
                    else:
                        await update.effective_message.reply_text("❌ Unknown field.", parse_mode="Markdown")
                        return
                    await session.commit()
                    await session.refresh(order)
                    card = _order_card_text(order)
                except (ValueError, TypeError):
                    await update.effective_message.reply_text(
                        f"❌ Invalid value `{new_val}` for *{field}*. Please try again.",
                        parse_mode="Markdown"
                    )
                    return

            # Sync the changed field to Google Sheets in the background
            import asyncio as _asyncio
            _asyncio.create_task(sheets.update_order_field_in_sheets(order_id, field, new_val))

            await update.effective_message.reply_text(
                f"✅ *Order updated!*\n\n{card}",
                parse_mode="Markdown",
                reply_markup=_order_action_keyboard(order_id)
            )
            return

        if role in ADMIN_ROLES:
            # --- Handle awaiting search query ---
            if context.user_data.get("awaiting_search"):
                context.user_data["awaiting_search"] = False
                query_str = text.strip()
                async with async_session() as session:
                    orders = await analytics.search_orders(session, query_str)
                if not orders:
                    await update.effective_message.reply_text(
                        f"🔍 No orders found for *\"{query_str}\"*.", parse_mode="Markdown",
                        reply_markup=get_main_menu_keyboard()
                    )
                    return
                await update.effective_message.reply_text(
                    f"🔍 *{len(orders)} result(s) for \"{query_str}\":*", parse_mode="Markdown"
                )
                for order in orders:
                    await update.effective_message.reply_text(
                        _order_card_text(order), parse_mode="Markdown",
                        reply_markup=_order_action_keyboard(order.order_id)
                    )
                return

            # --- Handle awaiting stock quantity from low stock alert button ---
            if context.user_data.get("awaiting_setstock_product"):
                product_name = context.user_data.pop("awaiting_setstock_product")
                try:
                    quantity = int(text.strip())
                except ValueError:
                    await update.effective_message.reply_text("❌ Please send a valid number.", parse_mode="Markdown")
                    context.user_data["awaiting_setstock_product"] = product_name  # restore state
                    return
                from src.db.models import Product
                async with async_session() as session:
                    result = await session.execute(select(Product).where(Product.name == product_name))
                    product = result.scalar_one_or_none()
                    if product:
                        product.current_stock = quantity
                    else:
                        session.add(Product(name=product_name, current_stock=quantity))
                    await session.commit()
                await update.effective_message.reply_text(
                    f"✅ *Stock Updated!*\n\n📦 *{product_name}*: {quantity} units",
                    parse_mode="Markdown",
                    reply_markup=get_main_menu_keyboard()
                )
                return

            # Check if we are waiting for a spreadsheet name
            if context.user_data.get("awaiting_sheet_name"):
                input_text = text.strip()
                import re
                
                # Extract ID if a full URL is provided
                match = re.search(r"/d/([a-zA-Z0-9-_]+)", input_text)
                sheet_id = match.group(1) if match else input_text
                
                await update.effective_message.reply_text(f"⏳ Verifying connection to ID: `{sheet_id}`...", parse_mode="Markdown")

                result = await check_google_sheets_connection(sheet_id)
                if result["success"]:
                    await config_service.set_active_sheet_name(sheet_id)
                    await config_service.set_active_sheet_url(result["url"])
                    context.user_data["awaiting_sheet_name"] = False
                    msg = f"✅ **Success!** Linked to Spreadsheet ID: `{sheet_id}`\n\nAll new orders will now be synced to this spreadsheet."
                    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Open Main Menu", callback_data="cmd_main_menu")]])
                    await update.effective_message.reply_text(msg, parse_mode="Markdown", reply_markup=keyboard)
                else:
                    msg = f"❌ **Connection Failed**\n\nError: {result['error']}\n\nPlease make sure the ID/URL is correct and the sheet is shared with the service account email."
                    keyboard = InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Try Again", callback_data="cmd_prompt_sheet_name")],
                        [InlineKeyboardButton("❌ Cancel", callback_data="cmd_manage_sheets")]
                    ])
                    await update.effective_message.reply_text(msg, parse_mode="Markdown", reply_markup=keyboard)
                return

            # --- Handle awaiting schedule time input ---
            if context.user_data.get("awaiting_schedule_time_for"):
                import re
                job_id = context.user_data["awaiting_schedule_time_for"]
                time_input = text.strip()
                if not re.match(r"^\d{1,2}:\d{2}$", time_input):
                    await update.effective_message.reply_text(
                        "❌ *Invalid format.*\n\nPlease send the time as `HH:MM` (24-hour).\nExample: `21:30` for 9:30 PM",
                        parse_mode="Markdown"
                    )
                    return
                parts = time_input.split(":")
                h, m = int(parts[0]), int(parts[1])
                if not (0 <= h <= 23 and 0 <= m <= 59):
                    await update.effective_message.reply_text(
                        "❌ *Invalid time.*\n\nHours must be 00–23 and minutes 00–59.\nExample: `23:59` for 11:59 PM",
                        parse_mode="Markdown"
                    )
                    return
                context.user_data.pop("awaiting_schedule_time_for")
                from src.scheduler.report_scheduler import reschedule_job_time
                success = await reschedule_job_time(job_id, h, m)
                if success:
                    job_name = SCHEDULE_JOBS[job_id]["name"]
                    keyboard = InlineKeyboardMarkup([[
                        InlineKeyboardButton("⚙️ Back to Schedule", callback_data="cmd_schedule_menu")
                    ]])
                    await update.effective_message.reply_text(
                        f"✅ *Schedule Updated!*\n\n"
                        f"{job_name} will now run at *{h:02d}:{m:02d}* (Dhaka time).\n\n"
                        f"_The change takes effect immediately — no restart needed._",
                        parse_mode="Markdown",
                        reply_markup=keyboard
                    )
                else:
                    context.user_data["awaiting_schedule_time_for"] = job_id
                    await update.effective_message.reply_text(
                        "❌ Failed to update the schedule. Please try again.",
                        parse_mode="Markdown"
                    )
                return

            msg = "🤔 **I didn't quite understand that.**\n\n*(You are an Admin. Are you trying to access your Dashboard?)*"
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Open Main Menu", callback_data="cmd_main_menu")]])
            await update.effective_message.reply_text(msg, parse_mode="Markdown", reply_markup=keyboard)
        else:
            # --- Moderator: awaiting search query ---
            if context.user_data.get("awaiting_mod_search"):
                context.user_data["awaiting_mod_search"] = False
                query_str = text.strip()
                async with async_session() as session:
                    orders = await analytics.search_my_orders(session, query_str, user_id)
                if not orders:
                    await update.effective_message.reply_text(
                        f"🔍 No orders found for *\"{query_str}\"*.",
                        parse_mode="Markdown"
                    )
                    return
                await update.effective_message.reply_text(
                    f"🔍 *{len(orders)} result(s) for \"{query_str}\":*", parse_mode="Markdown"
                )
                for order in orders:
                    await update.effective_message.reply_text(
                        _order_card_text(order), parse_mode="Markdown",
                        reply_markup=_mod_order_action_keyboard(order.order_id)
                    )
                return

            # --- Moderator: low stock step 1 — product name ---
            if context.user_data.get("awaiting_mod_lowstock_name"):
                context.user_data["awaiting_mod_lowstock_name"] = False
                typed_name = text.strip().title()

                # Validate against known products
                import difflib
                async with async_session() as session:
                    all_products = await analytics.get_all_products(session)
                product_names = [p.name for p in all_products]

                # Exact match (case-insensitive)
                exact_match = next((n for n in product_names if n.lower() == typed_name.lower()), None)

                if exact_match:
                    prod = next((p for p in all_products if p.name == exact_match), None)
                    stock_info = f"📊 Current stock: *{prod.current_stock}*" if prod else "📊 _(not tracked)_"
                    context.user_data["awaiting_mod_lowstock_msg"] = exact_match
                    await update.effective_message.reply_text(
                        f"✅ Product: *{exact_match}*\n{stock_info}\n\n"
                        f"⚠️ *Step 2 of 2* — Describe the issue\n_(e.g. 'Almost finished, need restock soon')_:",
                        parse_mode="Markdown"
                    )
                else:
                    # Try fuzzy matching
                    close_matches = difflib.get_close_matches(typed_name, product_names, n=3, cutoff=0.5)
                    if close_matches:
                        buttons = [
                            [InlineKeyboardButton(f"✅ {name}", callback_data=f"cmd_lowstock_pick_{name[:42]}")]
                            for name in close_matches
                        ]
                        buttons.append([InlineKeyboardButton(f"📋 Report \"{typed_name[:30]}\" anyway", callback_data=f"cmd_lowstock_anyway_{typed_name[:42]}")])
                        buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="cmd_main_menu")])
                        await update.effective_message.reply_text(
                            f"⚠️ *Product Not Found*\n\n"
                            f"No product named *\"{typed_name}\"* found.\n\n"
                            f"Did you mean one of these?",
                            parse_mode="Markdown",
                            reply_markup=InlineKeyboardMarkup(buttons)
                        )
                    else:
                        # No close matches — allow report anyway
                        buttons = [
                            [InlineKeyboardButton(f"📋 Report \"{typed_name[:30]}\" anyway", callback_data=f"cmd_lowstock_anyway_{typed_name[:42]}")],
                            [InlineKeyboardButton("❌ Cancel", callback_data="cmd_main_menu")]
                        ]
                        await update.effective_message.reply_text(
                            f"⚠️ *Product Not Found*\n\n"
                            f"*\"{typed_name}\"* is not in our product records.\n\n"
                            f"You can still report it, or cancel and verify the name in 📦 Check Stock.",
                            parse_mode="Markdown",
                            reply_markup=InlineKeyboardMarkup(buttons)
                        )
                return

            # --- Moderator: low stock step 2 — description ---
            if context.user_data.get("awaiting_mod_lowstock_msg"):
                product_name = context.user_data.pop("awaiting_mod_lowstock_msg")
                description = text.strip()
                reporter_name = update.effective_user.full_name or "A moderator"
                await _send_lowstock_alert(product_name, reporter_name, description)
                await update.effective_message.reply_text(
                    f"✅ Admin notified about low stock for *{product_name}*.",
                    parse_mode="Markdown"
                )
                return

            msg = (
                "🤔 **I didn't quite understand that.**\n\n"
                "If you are trying to submit a new order, please make sure your message begins exactly with `#ORDER`.\n\n"
                "*(I only understand structured order formats or menu commands!)*"
            )
            await update.effective_message.reply_text(msg, parse_mode="Markdown")
        return

    parsed = parse_order_message(text)
    if not parsed:
        await update.effective_message.reply_text(
            "❌ *Invalid order format.* Please use:\n\n"
            "`#ORDER`\n"
            "`Product: Exact Product Name`\n"
            "`Qty: 1`\n"
            "`Price: 500`\n"
            "`Phone: 017XXXXXXXX`\n"
            "`Status: PAID` _(optional, defaults to PENDING)_",
            parse_mode="Markdown"
        )
        return

    user_id = str(update.effective_user.id)
    from src.auth.roles import get_user_platform, get_user_role as _get_role
    user_platform = await get_user_platform(user_id)

    # Priority: 1. Tag in message (#FB, #WA), 2. User's assigned platform
    final_platform = parsed.platform or user_platform

    # If platform still unknown, admin defaults to TELEGRAM; moderator must tag
    if final_platform is None:
        user_role = await _get_role(user_id)
        if user_role in ADMIN_ROLES:
            final_platform = PlatformEnum.TELEGRAM
        else:
            await update.effective_message.reply_text(
                "❌ *Platform Not Set*\n\n"
                "Your account has no platform assigned. Add a tag to your order:\n\n"
                "`#WA` for WhatsApp orders\n"
                "`#FB` for Facebook orders\n\n"
                "Example:\n"
                "`#ORDER #WA`\n"
                "`Product: ...`\n"
                "`Qty: ...`\n"
                "`Price: ...`",
                parse_mode="Markdown"
            )
            return

    async with async_session() as session:
        new_order = await process_telegram_order(parsed, update.effective_message.message_id, session, platform=final_platform, created_by_id=user_id)
        
        if new_order:
            status_icon = "✅ PAID" if new_order.payment_status.value == "PAID" else "⏳ PENDING"
            confirm_msg = (
                f"✅ *Order Saved Successfully!*\n\n"
                f"🆔 ID: `{new_order.order_id}`\n"
                f"📦 Product: {new_order.product_name}\n"
                f"🔢 Qty: {new_order.quantity}  |  💰 ৳{float(new_order.price):,.0f}\n"
                f"📱 Phone: {new_order.phone_number or '—'}\n"
                f"🌐 Platform: {new_order.platform.value}\n"
                f"💳 Status: {status_icon}\n"
                f"🕐 {new_order.timestamp.strftime('%d %b %Y, %I:%M %p')}"
            )
            # Build action buttons based on payment status
            action_buttons = [InlineKeyboardButton("✏️ Edit Order", callback_data=f"cmd_edit_{new_order.order_id}")]
            if new_order.payment_status.value == "PENDING":
                action_buttons.insert(0, InlineKeyboardButton("✅ Mark as Paid", callback_data=f"cmd_markpaid_{new_order.order_id}"))
            confirm_keyboard = InlineKeyboardMarkup([action_buttons])
            await update.effective_message.reply_text(
                confirm_msg, parse_mode="Markdown", reply_markup=confirm_keyboard
            )
        else:
            await update.effective_message.reply_text("❌ Failed to process order!")
