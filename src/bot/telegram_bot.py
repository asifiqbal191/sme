import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from src.core.config import settings
from src.db.session import async_session
from src.services import analytics, sheets
from src.services.parser import parse_order_message
from src.db.models import Order, PlatformEnum
import asyncio

logger = logging.getLogger(__name__)

def get_main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("📊 Today's Sales (All)", callback_data="cmd_today_all")],
        [
            InlineKeyboardButton("🟦 Facebook Sales", callback_data="cmd_today_FACEBOOK"),
            InlineKeyboardButton("🟢 WhatsApp Sales", callback_data="cmd_today_WHATSAPP")
        ],
        [InlineKeyboardButton("📋 Recent Orders", callback_data="cmd_orders_all")],
        [InlineKeyboardButton("🏆 Top Product", callback_data="cmd_top")],
        [InlineKeyboardButton("⏳ Pending Orders", callback_data="cmd_pending")],
        [InlineKeyboardButton("📊 Google Sheet", callback_data="cmd_check_sheets")]
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

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    welcome_text = "Welcome to the Multi-Platform Order Tracking Agent 🤖\n\nPlease select an option below:"
    await update.effective_message.reply_text(welcome_text, reply_markup=get_main_menu_keyboard())

async def chatid_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Returns the current chat ID — useful for configuring scheduled reports."""
    chat_id = update.effective_chat.id
    await update.effective_message.reply_text(
        f"🆔 Your Chat ID is: `{chat_id}`\n\nAdd this to your `.env` file as:\n`TELEGRAM_CHAT_ID=\"{chat_id}\"`",
        parse_mode="Markdown"
    )

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

async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_today_sales(update, platform=None)

async def orders_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_recent_orders(update, platform=None)

async def top_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with async_session() as session:
        top_product = await analytics.get_weekly_top_product(session)
        if top_product:
            msg = f"🏆 *Top Product (Last 7 Days)*\n{top_product['product_name']}\nSold: {top_product['quantity']} units"
            await update.effective_message.reply_markdown(msg, reply_markup=get_main_menu_keyboard())
        else:
            await update.effective_message.reply_text("No sales recorded in the last 7 days.", reply_markup=get_main_menu_keyboard())

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
    result = await sheets.check_google_sheets_connection()
    if result["success"]:
        msg = (
            f"✅ <b>Connected to Google Sheets</b>\n"
            f"Total Rows: {result['count']}\n\n"
            f"📄 <b>Open Sheet:</b>\n{result['url']}"
        )
        keyboard = [[InlineKeyboardButton("📄 Open Sheet", url=result["url"])]]
        keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data="cmd_main_menu")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        if edit and update.callback_query:
            await update.callback_query.edit_message_text(msg, parse_mode="HTML", reply_markup=reply_markup)
        else:
            await update.effective_message.reply_html(msg, reply_markup=reply_markup)
    else:
        msg = result["error"]
        logger.error(f"Sheet check failed: {msg}")
        if edit and update.callback_query:
            await update.callback_query.edit_message_text(msg, reply_markup=get_main_menu_keyboard())
        else:
            await update.effective_message.reply_text(msg, reply_markup=get_main_menu_keyboard())

async def check_sheets_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_sheets_check(update, edit=False)


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
    elif query.data == "cmd_check_sheets":
        await _send_sheets_check(update, edit=True)
    elif query.data == "cmd_main_menu":
        await start_command(update, context)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Processes incoming text messages for orders."""
    text = update.effective_message.text
    if not text or not text.strip().upper().startswith("#ORDER"):
        return

    parsed = parse_order_message(text)
    if not parsed:
        await update.effective_message.reply_text("❌ Invalid order format. Please use:\n#ORDER\nID: ...\nProduct: ...\nQty: ...\nPrice: ...")
        return

    async with async_session() as session:
        # Create Order
        new_order = Order(
            order_id=parsed.order_id or f"ORD-{update.effective_message.message_id}",
            product_name=parsed.product_name,
            quantity=parsed.quantity,
            price=parsed.price,
            platform=PlatformEnum.TELEGRAM
        )
        session.add(new_order)
        await session.commit()
        await session.refresh(new_order)

        # Push to Google Sheets (Background)
        order_dict = {
            "id": str(new_order.id),
            "order_id": new_order.order_id,
            "product_name": new_order.product_name,
            "quantity": new_order.quantity,
            "price": float(new_order.price),
            "platform": new_order.platform.value,
            "timestamp": new_order.timestamp.isoformat(),
            "payment_status": new_order.payment_status.value
        }
        
        # We fire and forget the push to sheets
        asyncio.create_task(sheets.push_to_google_sheets(order_dict))
        
        logger.info(f"New Telegram order created: {new_order.order_id}")
        await update.effective_message.reply_text(f"✅ Order {new_order.order_id} recorded and synced to Google Sheets!")


async def create_bot_application() -> Application:
    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()
    return app
