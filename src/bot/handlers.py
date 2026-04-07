import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import ContextTypes

from src.core.config import settings
from src.db.session import async_session
from src.services import analytics, sheets
from src.services.parser import parse_order_message
from src.services.order_service import process_telegram_order
from sqlalchemy import select
from src.db.models import PlatformEnum, Order, Payment, PaymentStatusEnum
from src.services import config_service
from src.services.sheets import check_google_sheets_connection

from src.auth.roles import (
    require_admin,
    require_moderator_or_admin,
    generate_invite_code,
    generate_admin_invite_code,
    redeem_invite_code,
    add_moderator,
    set_ban_status,
    get_all_moderators,
    get_user_role,
    get_secondary_admin,
    remove_secondary_admin,
    RoleEnum
)

logger = logging.getLogger(__name__)

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
        [InlineKeyboardButton("🎟️ Generate Invite Link", callback_data="cmd_generate_invite")],
        [InlineKeyboardButton("👥 List Moderators", callback_data="cmd_list_mods")],
        [InlineKeyboardButton("👑 Admin Management", callback_data="cmd_admin_mgmt")],
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

async def join_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.effective_message.reply_text("❌ Please provide an invite code. Example: `/join INV-ABCD123`")
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
async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_today_sales(update, platform=None)

@require_admin
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
    ]
    
    is_admin_cmd = False
    for prefix in admin_only_prefixes:
        if query.data.startswith(prefix):
            is_admin_cmd = True
            break
            
    if is_admin_cmd and role != RoleEnum.ADMIN:
        await query.answer("⛔ Access Denied. Admin privileges required.", show_alert=True)
        return

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
    elif query.data == "cmd_my_stats":
        await moderator_stats_command(update, context)

    # --- Admin: Update Stock from low stock alert button ---
    elif query.data.startswith("cmd_admin_setstock_"):
        if role != RoleEnum.ADMIN:
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
        user_id = str(query.from_user.id)
        role = await get_user_role(user_id)
        if role == RoleEnum.ADMIN:
            await query.edit_message_text("Welcome to the Multi-Platform Order Tracking Agent 🤖\n\nPlease select an option below:", reply_markup=get_main_menu_keyboard())
        else:
            await query.edit_message_text("Welcome back! Use the keyboard below to check your stats or just send an #ORDER.")

    elif query.data == "cmd_admin_mgmt":
        if str(query.from_user.id) != str(settings.TELEGRAM_CHAT_ID):
            await query.answer("⛔ Only the primary admin can manage admin access.", show_alert=True)
            return
        secondary = await get_secondary_admin()
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
        code = await generate_admin_invite_code()
        if code is None:
            await query.answer("⚠️ A secondary admin already exists. Remove them first.", show_alert=True)
        else:
            forward_msg = (
                f"👑 *You have been invited as an Admin!*\n\n"
                f"Open the bot @SME\\_management\\_bot and send:\n"
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
        success = await remove_secondary_admin(admin_id)
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
            if role != RoleEnum.ADMIN and order.created_by_id != user_id:
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
        await query.edit_message_text(
            f"⚠️ *Cancel Order `{order_id}`?*\n\nThis will permanently delete the order.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🗑️ Yes, Delete It", callback_data=f"cmd_confirmcancel_{order_id}")],
                [InlineKeyboardButton("↩️ No, Keep It",   callback_data="cmd_main_menu")]
            ])
        )

    # --- Cancel order: confirmed, delete ---
    elif query.data.startswith("cmd_confirmcancel_"):
        order_id = query.data.replace("cmd_confirmcancel_", "")
        async with async_session() as session:
            result = await session.execute(select(Order).where(Order.order_id == order_id))
            order = result.scalar_one_or_none()
            if not order:
                await query.answer("❌ Order not found.", show_alert=True)
                return
            await session.delete(order)
            await session.commit()
        await query.edit_message_text(
            f"🗑️ Order `{order_id}` has been cancelled and removed.",
            parse_mode="Markdown"
        )


# --- Order Processing (Moderator & Admin) ---

@require_moderator_or_admin
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
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Processes incoming text messages for orders."""
    text = update.effective_message.text

    # Handle persistent keyboard "Main Menu" button tap
    if text and text.strip() == "🏠 Main Menu":
        user_id = str(update.effective_user.id)
        role = await get_user_role(user_id)
        if role == RoleEnum.ADMIN:
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
        if role == RoleEnum.ADMIN:
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
                if role != RoleEnum.ADMIN and order.created_by_id != user_id:
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

        if role == RoleEnum.ADMIN:
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
        if user_role == RoleEnum.ADMIN:
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
