import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from src.db.session import async_session
from src.services import analytics, sheets
from src.services.parser import parse_order_message
from src.services.order_service import process_telegram_order
from src.db.models import PlatformEnum
from src.services import config_service
from src.services.sheets import check_google_sheets_connection

from src.auth.roles import (
    require_admin,
    require_moderator_or_admin,
    generate_invite_code,
    redeem_invite_code,
    add_moderator,
    set_ban_status,
    get_all_moderators,
    get_user_role,
    RoleEnum
)

logger = logging.getLogger(__name__)

def get_main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("📊 Today's Sales", callback_data="cmd_today_all")],
        [
            InlineKeyboardButton("📅 Weekly", callback_data="cmd_weekly"),
            InlineKeyboardButton("📅 Monthly", callback_data="cmd_monthly")
        ],
        [
            InlineKeyboardButton("📈 Growth", callback_data="cmd_growth"),
            InlineKeyboardButton("🚨 Alerts", callback_data="cmd_alerts")
        ],
        [InlineKeyboardButton("📋 Recent Orders", callback_data="cmd_orders_all")],
        [InlineKeyboardButton("🏆 Top Product", callback_data="cmd_top")],
        [InlineKeyboardButton("⏳ Pending Orders", callback_data="cmd_pending")],
        [
            InlineKeyboardButton("📊 Google Sheet", callback_data="cmd_check_sheets"),
            InlineKeyboardButton("⚙️ Settings", callback_data="cmd_settings")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_settings_keyboard():
    keyboard = [
        [InlineKeyboardButton("🎟️ Generate Invite Link", callback_data="cmd_generate_invite")],
        [InlineKeyboardButton("👥 List Moderators", callback_data="cmd_list_mods")],
        [InlineKeyboardButton("📊 Manage Spreadsheet", callback_data="cmd_manage_sheets")],
        [InlineKeyboardButton("🏠 Back to Main Menu", callback_data="cmd_main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

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

@require_admin
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    welcome_text = "Welcome to the Multi-Platform Order Tracking Agent 🤖\n\nPlease select an option below:"
    await update.effective_message.reply_text(welcome_text, reply_markup=get_main_menu_keyboard())

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

async def _do_generate_invite(update: Update, platform: PlatformEnum):
    code = await generate_invite_code(platform)
    plat_icon = "🟦 Facebook" if platform == PlatformEnum.FACEBOOK else "🟢 WhatsApp"
    
    admin_msg = f"🎟️ **New {plat_icon} Invite Generated!**\n\nForward or copy the message below to your new moderator:"
    
    forward_msg = (
        f"👋 **Welcome to the team!**\n"
        f"You have been invited to access the Order Tracking Bot as a {plat_icon} Moderator.\n\n"
        f"**Step 1:** To connect your account, open the bot here 👉 @SME\_management\_bot and send this exact code:\n"
        f"`/join {code}`\n\n"
        f"**Step 2:** After joining, whenever you receive a new order, simply copy-paste and fill out this format here:\n\n"
        f"`#ORDER`\n"
        f"`Product: (Write Name Here)`\n"
        f"`Qty: 1`\n"
        f"`Price: 500`"
    )
    
    # Add Main Menu button to the forwarded message for easier navigation
    menu_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="cmd_main_menu")]])
    
    if update.callback_query:
        await update.callback_query.edit_message_text(admin_msg, parse_mode="Markdown", reply_markup=get_settings_keyboard())
        await update.callback_query.message.reply_text(forward_msg, parse_mode="Markdown", reply_markup=menu_keyboard)
    else:
        await update.effective_message.reply_text(admin_msg, parse_mode="Markdown", reply_markup=get_settings_keyboard())
        await update.effective_message.reply_text(forward_msg, parse_mode="Markdown", reply_markup=menu_keyboard)

async def join_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.effective_message.reply_text("❌ Please provide an invite code. Example: `/join INV-ABCD123`")
        return
        
    code = context.args[0]
    user_id = str(update.effective_user.id)
    full_name = update.effective_user.full_name or "Moderator"
    
    result = await redeem_invite_code(user_id, full_name, code)
    if result is True:
        welcome_msg = (
            f"✅ **Welcome {full_name}!** You have successfully joined as a Moderator.\n\n"
            "Here is how to use the bot:\n"
            "Whenever you receive a new order, simply send a message in this exact format:\n\n"
            "`#ORDER`\n"
            "`Product: Exact Product Name`\n"
            "`Qty: 1`\n"
            "`Price: 500`\n\n"
            "I will save it and automatically update the Google Sheets database!"
        )
        menu_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Open Main Menu", callback_data="cmd_main_menu")]])
        await update.effective_message.reply_text(welcome_msg, parse_mode="Markdown", reply_markup=menu_keyboard)
    else:
        await update.effective_message.reply_text(f"❌ Failed to join: {result}")

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

async def _send_recent_orders(update: Update, platform: PlatformEnum = None, edit: bool = False):
    async with async_session() as session:
        orders = await analytics.get_recent_orders(session, limit=10, platform=platform)
        
        title = "📋 *Recent Orders*"
        if platform == PlatformEnum.FACEBOOK:
            title = "🟦 *Recent Facebook Orders*"
        elif platform == PlatformEnum.WHATSAPP:
            title = "🟢 *Recent WhatsApp Orders*"
            
        if not orders:
            text = f"{title}\n\nNo orders found."
        else:
            text = f"{title}\n\n"
            for o in orders:
                text += f"ID: {o.order_id} - {o.product_name} (BDT {o.price})\nPlatform: {o.platform.value}\n---\n"
        
        if edit:
            await update.effective_message.edit_text(text, parse_mode="Markdown", reply_markup=get_orders_filter_keyboard())
        else:
            await update.effective_message.reply_markdown(text, reply_markup=get_orders_filter_keyboard())

@require_admin
async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_today_sales(update, platform=None)

@require_admin
async def orders_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_recent_orders(update, platform=None)

@require_admin
async def top_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with async_session() as session:
        top_product = await analytics.get_weekly_top_product(session)
        if top_product:
            msg = f"🏆 *Top Product (Last 7 Days)*\n{top_product['product_name']}\nSold: {top_product['quantity']} units"
            await update.effective_message.reply_markdown(msg, reply_markup=get_main_menu_keyboard())
        else:
            await update.effective_message.reply_text("No sales recorded in the last 7 days.", reply_markup=get_main_menu_keyboard())

@require_admin
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

@require_admin
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
async def pending_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with async_session() as session:
        orders = await analytics.get_pending_orders(session, limit=5)
        if not orders:
            await update.effective_message.reply_text("No pending orders found.", reply_markup=get_main_menu_keyboard())
            return
            
        text = "⏳ *Recent Pending Orders*\n\n"
        for o in orders:
            text += f"ID: {o.order_id}\nProduct: {o.product_name} (৳{o.price})\nPlatform: {o.platform.value}\n---\n"
        await update.effective_message.reply_markdown(text, reply_markup=get_main_menu_keyboard())

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
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    logger.info(f"Button clicked: {query.data}")
    
    if query.data == "cmd_today_all":
        await _send_today_sales(update, platform=None)
    elif query.data == "cmd_today_FACEBOOK":
        await _send_today_sales(update, platform=PlatformEnum.FACEBOOK)
    elif query.data == "cmd_today_WHATSAPP":
        await _send_today_sales(update, platform=PlatformEnum.WHATSAPP)
    elif query.data == "cmd_orders_all":
        await _send_recent_orders(update, platform=None, edit=True)
    elif query.data == "cmd_orders_FACEBOOK":
        await _send_recent_orders(update, platform=PlatformEnum.FACEBOOK, edit=True)
    elif query.data == "cmd_orders_WHATSAPP":
        await _send_recent_orders(update, platform=PlatformEnum.WHATSAPP, edit=True)
    elif query.data == "cmd_top":
        await top_command(update, context)
    elif query.data == "cmd_pending":
        await pending_command(update, context)
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
    elif query.data == "cmd_generate_invite":
        await generate_invite_command(update, context)
    elif query.data == "cmd_gen_invite_FACEBOOK":
        await _do_generate_invite(update, PlatformEnum.FACEBOOK)
    elif query.data == "cmd_gen_invite_WHATSAPP":
        await _do_generate_invite(update, PlatformEnum.WHATSAPP)
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
    elif query.data == "cmd_main_menu":
        await query.edit_message_text("Welcome to the Multi-Platform Order Tracking Agent 🤖\n\nPlease select an option below:", reply_markup=get_main_menu_keyboard())

    elif query.data == "cmd_manage_sheets":
        sheet_name = await config_service.get_active_sheet_name()
        status = f"🟢 Connected to: `{sheet_name}`" if sheet_name else "🔴 *Not Connected*"
        
        # Get service account email from settings/file
        import json
        try:
            with open("service_account.json", "r") as f:
                creds = json.load(f)
                email = creds.get("client_email", "Not Found")
        except:
            email = "service_account.json not found"

        text = (
            "📊 **Manage Spreadsheet Connection**\n\n"
            f"Status: {status}\n\n"
            "**Instructions:**\n"
            "1. Create a Google Spreadsheet.\n"
            f"2. Share it with this email (Editor access):\n`{email}`\n"
            "3. Click the button below to link it to the bot.\n"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 Set/Change Connection", callback_data="cmd_prompt_sheet_name")],
            [InlineKeyboardButton("🔙 Back to Settings", callback_data="cmd_settings")]
        ])
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)

    elif query.data == "cmd_prompt_sheet_name":
        context.user_data["awaiting_sheet_name"] = True
        text = "📝 **Please send the exact name of your Google Spreadsheet.**\n\n*(Make sure you have already shared it with the service account email!)*"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cmd_manage_sheets")]])
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)


# --- Order Processing (Moderator & Admin) ---

@require_moderator_or_admin
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Processes incoming text messages for orders."""
    text = update.effective_message.text
    if not text or not text.strip().upper().startswith("#ORDER"):
        from src.auth.roles import get_user_role
        from src.db.models import RoleEnum
        
        user_id = str(update.effective_user.id)
        role = await get_user_role(user_id)
        
        if role == RoleEnum.ADMIN:
            # Check if we are waiting for a spreadsheet name
            if context.user_data.get("awaiting_sheet_name"):
                sheet_name = text.strip()
                await update.effective_message.reply_text(f"⏳ Verifying connection to: `{sheet_name}`...", parse_mode="Markdown")
                
                result = await check_google_sheets_connection(sheet_name)
                if result["success"]:
                    await config_service.set_active_sheet_name(sheet_name)
                    await config_service.set_active_sheet_url(result["url"])
                    context.user_data["awaiting_sheet_name"] = False
                    msg = f"✅ **Success!** Linked to: `{sheet_name}`\n\nAll new orders will now be synced to this spreadsheet."
                    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Open Main Menu", callback_data="cmd_main_menu")]])
                    await update.effective_message.reply_text(msg, parse_mode="Markdown", reply_markup=keyboard)
                else:
                    msg = f"❌ **Connection Failed**\n\nError: {result['error']}\n\nPlease make sure the name is exact and the sheet is shared with the service account email."
                    keyboard = InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Try Again", callback_data="cmd_prompt_sheet_name")],
                        [InlineKeyboardButton("❌ Cancel", callback_data="cmd_manage_sheets")]
                    ])
                    await update.effective_message.reply_text(msg, parse_mode="Markdown", reply_markup=keyboard)
                return

            msg = "🤔 **I didn't quite understand that.**\n\n*(You are an Admin. Are you trying to access your Dashboard?)*"
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Open Main Menu", callback_data="cmd_main_menu")]])
            await update.effective_message.reply_text(msg, parse_mode="Markdown", reply_markup=keyboard)
        else:
            msg = (
                "🤔 **I didn't quite understand that.**\n\n"
                "If you are trying to submit a new order, please make sure your message begins exactly with `#ORDER`.\n\n"
                "*(I only understand structured order formats or menu commands!)*"
            )
            await update.effective_message.reply_text(msg, parse_mode="Markdown")
        return

    parsed = parse_order_message(text)
    if not parsed:
        await update.effective_message.reply_text("❌ Invalid order format. Please use:\n#ORDER\nProduct: ...\nQty: ...\nPrice: ...\nStatus: PAID/PENDING (Optional)")
        return

    user_id = str(update.effective_user.id)
    from src.auth.roles import get_user_platform
    user_platform = await get_user_platform(user_id)
    
    # Priority: 1. Tag in message (#FB, #WA), 2. User's default platform
    final_platform = parsed.platform or user_platform

    async with async_session() as session:
        new_order = await process_telegram_order(parsed, update.effective_message.message_id, session, platform=final_platform)
        
        if new_order:
            await update.effective_message.reply_text(f"✅ Order Added Successfully\nID: {new_order.order_id}")
        else:
            await update.effective_message.reply_text("❌ Failed to process order!")
