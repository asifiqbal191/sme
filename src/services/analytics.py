import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text, and_, or_
from datetime import datetime, timedelta
import pytz
from src.db.models import Order, PlatformEnum, Product, User, RoleEnum, DHAKA_TZ
from typing import Optional

def _now_local():
    """Returns current local time as naive datetime (for DB comparison)."""
    return datetime.now(DHAKA_TZ).replace(tzinfo=None)

async def get_sales_for_range(
    session: AsyncSession,
    start_time: datetime,
    end_time: datetime,
    platform: Optional[PlatformEnum] = None,
    tenant_id: Optional[uuid.UUID] = None,
):
    """
    Returns total sales amount and total orders for a given time range.
    Pass tenant_id to explicitly scope to a tenant (bypasses with_loader_criteria).
    """
    conditions = [Order.timestamp >= start_time, Order.timestamp < end_time]
    if platform:
        conditions.append(Order.platform == platform)
    if tenant_id is not None:
        conditions.append(Order.tenant_id == tenant_id)

    query = select(
        func.sum(Order.price).label("total_sales"),
        func.count(Order.id).label("total_orders")
    ).where(and_(*conditions))

    result = await session.execute(query)
    row = result.first()

    return {
        "total_sales": float(row.total_sales or 0),
        "total_orders": int(row.total_orders or 0)
    }

async def get_daily_sales(session: AsyncSession, platform: Optional[PlatformEnum] = None, tenant_id: Optional[uuid.UUID] = None):
    """
    Returns total sales amount and total orders for today (Asia/Dhaka time).
    """
    now = _now_local()
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)

    return await get_sales_for_range(session, start_of_day, now, platform, tenant_id=tenant_id)

async def get_yesterday_sales(session: AsyncSession, platform: Optional[PlatformEnum] = None, tenant_id: Optional[uuid.UUID] = None):
    """
    Returns total sales amount and total orders for yesterday (Asia/Dhaka time).
    """
    now = _now_local()
    yesterday = now - timedelta(days=1)
    start_of_yesterday = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_yesterday = start_of_yesterday + timedelta(days=1)

    return await get_sales_for_range(session, start_of_yesterday, end_of_yesterday, platform, tenant_id=tenant_id)

async def get_weekly_top_product(session: AsyncSession, tenant_id: Optional[uuid.UUID] = None):
    seven_days_ago = _now_local() - timedelta(days=7)
    conditions = [Order.timestamp >= seven_days_ago]
    if tenant_id is not None:
        conditions.append(Order.tenant_id == tenant_id)

    query = select(
        Order.product_name,
        func.sum(Order.quantity).label("total_qty")
    ).where(and_(*conditions)).group_by(
        Order.product_name
    ).order_by(
        text("total_qty DESC")
    ).limit(1)

    result = await session.execute(query)
    row = result.first()
    if row:
        return {"product_name": row.product_name, "quantity": row.total_qty}
    return None

async def get_today_top_product(session: AsyncSession, tenant_id: Optional[uuid.UUID] = None):
    """Returns the top-selling product for today based on quantity sold, with its revenue."""
    now = _now_local()
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    conditions = [Order.timestamp >= start_of_day]
    if tenant_id is not None:
        conditions.append(Order.tenant_id == tenant_id)

    query = select(
        Order.product_name,
        func.sum(Order.quantity).label("total_qty"),
        func.sum(Order.price).label("total_revenue")
    ).where(and_(*conditions)).group_by(
        Order.product_name
    ).order_by(
        text("total_qty DESC")
    ).limit(1)

    result = await session.execute(query)
    row = result.first()
    if row:
        return {
            "product_name": row.product_name,
            "quantity": int(row.total_qty),
            "revenue": float(row.total_revenue or 0)
        }
    return None

async def get_top_product(session: AsyncSession, tenant_id: Optional[uuid.UUID] = None):
    """
    Returns the top-selling product for today based on quantity sold.
    """
    return await get_today_top_product(session, tenant_id=tenant_id)


async def get_weekly_sales(session: AsyncSession, tenant_id: Optional[uuid.UUID] = None):
    """Returns total sales amount for the last 7 days."""
    seven_days_ago = _now_local() - timedelta(days=7)
    conditions = [Order.timestamp >= seven_days_ago]
    if tenant_id is not None:
        conditions.append(Order.tenant_id == tenant_id)

    query = select(
        func.sum(Order.price).label("total_sales"),
        func.count(Order.id).label("total_orders")
    ).where(and_(*conditions))

    result = await session.execute(query)
    row = result.first()
    return {
        "total_sales": row.total_sales or 0,
        "total_orders": row.total_orders or 0
    }


async def get_monthly_sales(session: AsyncSession, tenant_id: Optional[uuid.UUID] = None):
    """Returns total sales amount for the last 30 days."""
    thirty_days_ago = _now_local() - timedelta(days=30)
    conditions = [Order.timestamp >= thirty_days_ago]
    if tenant_id is not None:
        conditions.append(Order.tenant_id == tenant_id)

    query = select(
        func.sum(Order.price).label("total_sales"),
        func.count(Order.id).label("total_orders")
    ).where(and_(*conditions))

    result = await session.execute(query)
    row = result.first()
    return {
        "total_sales": row.total_sales or 0,
        "total_orders": row.total_orders or 0
    }


async def get_monthly_top_product(session: AsyncSession, tenant_id: Optional[uuid.UUID] = None):
    """Returns the top-selling product for the last 30 days."""
    thirty_days_ago = _now_local() - timedelta(days=30)
    conditions = [Order.timestamp >= thirty_days_ago]
    if tenant_id is not None:
        conditions.append(Order.tenant_id == tenant_id)

    query = select(
        Order.product_name,
        func.sum(Order.quantity).label("total_qty")
    ).where(and_(*conditions)).group_by(
        Order.product_name
    ).order_by(
        text("total_qty DESC")
    ).limit(1)

    result = await session.execute(query)
    row = result.first()
    if row:
        return {"product_name": row.product_name, "quantity": row.total_qty}
    return None


async def get_recent_orders(session: AsyncSession, limit: int = 10, platform: Optional[PlatformEnum] = None, offset: int = 0, tenant_id: Optional[uuid.UUID] = None):
    conditions = []
    if platform:
        conditions.append(Order.platform == platform)
    if tenant_id is not None:
        conditions.append(Order.tenant_id == tenant_id)

    query = select(Order)
    if conditions:
        query = query.where(and_(*conditions))

    query = query.order_by(Order.timestamp.desc()).offset(offset).limit(limit)
    result = await session.execute(query)
    return result.scalars().all()

async def get_pending_orders(session: AsyncSession, limit: int = 10, platform: Optional[PlatformEnum] = None, tenant_id: Optional[uuid.UUID] = None):
    from src.db.models import PaymentStatusEnum
    conditions = [Order.payment_status == PaymentStatusEnum.PENDING]
    if platform:
        conditions.append(Order.platform == platform)
    if tenant_id is not None:
        conditions.append(Order.tenant_id == tenant_id)

    query = select(Order).where(and_(*conditions)).order_by(Order.timestamp.desc()).limit(limit)
    result = await session.execute(query)
    return result.scalars().all()

async def get_stock_predictions(session: AsyncSession, lookback_days: int = 30, tenant_id: Optional[uuid.UUID] = None):
    """
    Predicts when products will run out based on sales trends.
    Calculates average daily sales and days remaining.
    """
    # 1. Fetch all products for this tenant
    prod_conditions = []
    if tenant_id is not None:
        prod_conditions.append(Product.tenant_id == tenant_id)

    products_query = select(Product)
    if prod_conditions:
        products_query = products_query.where(and_(*prod_conditions))
    products_result = await session.execute(products_query)
    products = products_result.scalars().all()

    if not products:
        return []

    # 2. Calculate average daily sales for each product over lookback period
    start_date = _now_local() - timedelta(days=lookback_days)
    ord_conditions = [Order.timestamp >= start_date]
    if tenant_id is not None:
        ord_conditions.append(Order.tenant_id == tenant_id)

    sales_query = select(
        Order.product_name,
        func.sum(Order.quantity).label("total_qty")
    ).where(and_(*ord_conditions)).group_by(Order.product_name)

    sales_result = await session.execute(sales_query)
    sales_data = {row.product_name: float(row.total_qty) for row in sales_result}

    predictions = []
    for p in products:
        total_sold = sales_data.get(p.name, 0)
        avg_daily_sales = total_sold / lookback_days

        if avg_daily_sales > 0:
            days_remaining = p.current_stock / avg_daily_sales
        else:
            days_remaining = 999  # Large number instead of inf for easier formatting

        predictions.append({
            "product_name": p.name,
            "current_stock": p.current_stock,
            "avg_daily_sales": avg_daily_sales,
            "days_remaining": days_remaining
        })

    return predictions

async def get_revenue_breakdown(session: AsyncSession, start_time: datetime, end_time: datetime, limit: int = 3, tenant_id: Optional[uuid.UUID] = None):
    """
    Returns the top products by revenue (price * quantity) for a given time range.
    """
    conditions = [Order.timestamp >= start_time, Order.timestamp < end_time]
    if tenant_id is not None:
        conditions.append(Order.tenant_id == tenant_id)

    query = select(
        Order.product_name,
        func.sum(Order.price).label("total_revenue")
    ).where(and_(*conditions)).group_by(
        Order.product_name
    ).order_by(
        text("total_revenue DESC")
    ).limit(limit)

    result = await session.execute(query)
    rows = result.all()

    return [
        {"product_name": row.product_name, "revenue": float(row.total_revenue or 0)}
        for row in rows
    ]

async def search_orders(session: AsyncSession, query: str, limit: int = 10, tenant_id: Optional[uuid.UUID] = None):
    """Search all orders by product name, phone number, or order ID (admin use)."""
    conditions = [
        or_(
            Order.product_name.ilike(f"%{query}%"),
            Order.phone_number.ilike(f"%{query}%"),
            Order.order_id.ilike(f"%{query}%")
        )
    ]
    if tenant_id is not None:
        conditions.append(Order.tenant_id == tenant_id)

    result = await session.execute(
        select(Order).where(and_(*conditions)).order_by(Order.timestamp.desc()).limit(limit)
    )
    return result.scalars().all()


async def search_my_orders(session: AsyncSession, query: str, moderator_id: str, limit: int = 10, tenant_id: Optional[uuid.UUID] = None):
    """Search only the orders submitted by a specific moderator."""
    conditions = [
        Order.created_by_id == moderator_id,
        or_(
            Order.product_name.ilike(f"%{query}%"),
            Order.phone_number.ilike(f"%{query}%"),
            Order.order_id.ilike(f"%{query}%")
        )
    ]
    if tenant_id is not None:
        conditions.append(Order.tenant_id == tenant_id)

    result = await session.execute(
        select(Order).where(and_(*conditions)).order_by(Order.timestamp.desc()).limit(limit)
    )
    return result.scalars().all()


async def get_moderator_stats(session: AsyncSession, moderator_id: str, tenant_id: Optional[uuid.UUID] = None):
    """Returns today's sales stats for a single moderator."""
    now = _now_local()
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)

    conditions = [Order.timestamp >= start_of_day, Order.created_by_id == moderator_id]
    if tenant_id is not None:
        conditions.append(Order.tenant_id == tenant_id)

    query = select(
        func.sum(Order.price).label("total_sales"),
        func.count(Order.id).label("total_orders")
    ).where(and_(*conditions))

    result = await session.execute(query)
    row = result.first()

    return {
        "total_sales": float(row.total_sales or 0),
        "total_orders": int(row.total_orders or 0)
    }


async def get_all_moderators_stats(session: AsyncSession, tenant_id: Optional[uuid.UUID] = None) -> list[dict]:
    """Returns order stats (today / 7-day / all-time) for every active moderator."""
    mod_conditions = [User.role == RoleEnum.MODERATOR, User.is_banned == False]  # noqa: E712
    if tenant_id is not None:
        mod_conditions.append(User.tenant_id == tenant_id)

    mods_result = await session.execute(select(User).where(and_(*mod_conditions)))
    moderators = mods_result.scalars().all()
    if not moderators:
        return []

    now = _now_local()
    start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_of_week  = now - timedelta(days=7)

    async def _fetch(mid: str, extra_condition):
        conds = [Order.created_by_id == mid, extra_condition]
        if tenant_id is not None:
            conds.append(Order.tenant_id == tenant_id)
        r = await session.execute(
            select(
                func.count(Order.id).label("orders"),
                func.sum(Order.price).label("sales")
            ).where(and_(*conds))
        )
        row = r.first()
        return int(row.orders or 0), float(row.sales or 0)

    stats = []
    for mod in moderators:
        mid = mod.telegram_id
        today_orders,   today_sales   = await _fetch(mid, Order.timestamp >= start_of_today)
        week_orders,    week_sales    = await _fetch(mid, Order.timestamp >= start_of_week)
        alltime_orders, alltime_sales = await _fetch(mid, Order.id != None)  # noqa: E711

        stats.append({
            "name":           mod.full_name or "Unknown",
            "id":             mid,
            "platform":       mod.platform.value if mod.platform else "General",
            "today_orders":   today_orders,
            "today_sales":    today_sales,
            "week_orders":    week_orders,
            "week_sales":     week_sales,
            "alltime_orders": alltime_orders,
            "alltime_sales":  alltime_sales,
        })

    return stats


async def get_all_products(session: AsyncSession, tenant_id: Optional[uuid.UUID] = None) -> list:
    """Returns all products ordered by name."""
    q = select(Product).order_by(Product.name)
    if tenant_id is not None:
        q = q.where(Product.tenant_id == tenant_id)
    result = await session.execute(q)
    return result.scalars().all()
