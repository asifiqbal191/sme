"""
Dashboard API Router
--------------------
Serves all JSON endpoints consumed by the web dashboard frontend.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Query
from sqlalchemy import select, func, and_, case, text

from src.db.session import async_session
from src.db.models import Order, Product, User, Payment, PlatformEnum, PaymentStatusEnum, RoleEnum, DHAKA_TZ
from src.services import analytics

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _now_local():
    return datetime.now(DHAKA_TZ).replace(tzinfo=None)


# ─────────────────────────────────────────────
# 1. KPI Summary
# ─────────────────────────────────────────────
@router.get("/summary")
async def get_summary(days: int = Query(default=0, description="0=today, 7=week, 30=month")):
    """Returns KPI card data for the selected period."""
    now = _now_local()

    if days == 0:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        prev_start = start - timedelta(days=1)
        prev_end = start
        label = "Today"
    elif days == 7:
        start = now - timedelta(days=7)
        prev_start = start - timedelta(days=7)
        prev_end = start
        label = "Last 7 Days"
    else:
        start = now - timedelta(days=30)
        prev_start = start - timedelta(days=30)
        prev_end = start
        label = "Last 30 Days"

    async with async_session() as session:
        # Current period
        current = await analytics.get_sales_for_range(session, start, now)

        # Previous period (for trend)
        previous = await analytics.get_sales_for_range(session, prev_start, prev_end)

        # Payment status breakdown (current period)
        pay_q = select(
            Order.payment_status,
            func.count(Order.id).label("cnt"),
            func.sum(Order.price).label("amount")
        ).where(Order.timestamp >= start).group_by(Order.payment_status)
        pay_result = await session.execute(pay_q)
        payment_data = {str(r.payment_status): {"count": int(r.cnt), "amount": float(r.amount or 0)} for r in pay_result}

        # Active products & moderators
        active_products = await session.execute(
            select(func.count(func.distinct(Order.product_name))).where(Order.timestamp >= start)
        )
        active_mods = await session.execute(
            select(func.count(func.distinct(Order.created_by_id))).where(
                Order.timestamp >= start, Order.created_by_id != None  # noqa: E711
            )
        )

    total_sales = current["total_sales"]
    total_orders = current["total_orders"]
    prev_sales = previous["total_sales"]
    prev_orders = previous["total_orders"]

    # Growth calculations
    sales_growth = 0.0
    if prev_sales > 0:
        sales_growth = ((total_sales - prev_sales) / prev_sales) * 100
    elif total_sales > 0:
        sales_growth = 100.0

    orders_growth = 0.0
    if prev_orders > 0:
        orders_growth = ((total_orders - prev_orders) / prev_orders) * 100
    elif total_orders > 0:
        orders_growth = 100.0

    avg_order = total_sales / total_orders if total_orders > 0 else 0

    paid_info = payment_data.get("PaymentStatusEnum.PAID", payment_data.get("PAID", {"count": 0, "amount": 0}))
    pending_info = payment_data.get("PaymentStatusEnum.PENDING", payment_data.get("PENDING", {"count": 0, "amount": 0}))

    return {
        "label": label,
        "total_sales": total_sales,
        "total_orders": total_orders,
        "avg_order_value": round(avg_order, 2),
        "sales_growth": round(sales_growth, 1),
        "orders_growth": round(orders_growth, 1),
        "paid_orders": paid_info["count"],
        "paid_amount": paid_info["amount"],
        "pending_orders": pending_info["count"],
        "pending_amount": pending_info["amount"],
        "active_products": active_products.scalar() or 0,
        "active_moderators": active_mods.scalar() or 0,
    }


# ─────────────────────────────────────────────
# 2. Sales Trend (daily breakdown)
# ─────────────────────────────────────────────
@router.get("/sales-trend")
async def get_sales_trend(days: int = Query(default=30)):
    """Daily sales & order counts for the last N days."""
    now = _now_local()
    start = now - timedelta(days=days)

    async with async_session() as session:
        # Group orders by date
        q = select(
            func.date(Order.timestamp).label("day"),
            func.sum(Order.price).label("sales"),
            func.count(Order.id).label("orders")
        ).where(Order.timestamp >= start).group_by(func.date(Order.timestamp)).order_by(text("day"))

        result = await session.execute(q)
        rows = result.all()

    # Build complete date range (fill missing days with 0)
    data = []
    date_map = {str(r.day): {"sales": float(r.sales or 0), "orders": int(r.orders)} for r in rows}
    current = start.replace(hour=0, minute=0, second=0, microsecond=0)
    while current <= now:
        day_str = current.strftime("%Y-%m-%d")
        entry = date_map.get(day_str, {"sales": 0, "orders": 0})
        data.append({
            "date": day_str,
            "sales": entry["sales"],
            "orders": entry["orders"]
        })
        current += timedelta(days=1)

    return {"trend": data}


# ─────────────────────────────────────────────
# 3. Platform Distribution
# ─────────────────────────────────────────────
@router.get("/platform-split")
async def get_platform_split(days: int = Query(default=30)):
    """Order count and revenue by platform."""
    now = _now_local()
    start = now - timedelta(days=days) if days > 0 else now.replace(hour=0, minute=0, second=0, microsecond=0)

    async with async_session() as session:
        q = select(
            Order.platform,
            func.count(Order.id).label("orders"),
            func.sum(Order.price).label("sales")
        ).where(Order.timestamp >= start).group_by(Order.platform)

        result = await session.execute(q)
        rows = result.all()

    return {
        "platforms": [
            {
                "name": str(r.platform.value) if hasattr(r.platform, 'value') else str(r.platform),
                "orders": int(r.orders),
                "sales": float(r.sales or 0)
            }
            for r in rows
        ]
    }


# ─────────────────────────────────────────────
# 4. Top Products
# ─────────────────────────────────────────────
@router.get("/top-products")
async def get_top_products(days: int = Query(default=30), limit: int = Query(default=10)):
    """Top products by revenue."""
    now = _now_local()
    start = now - timedelta(days=days) if days > 0 else now.replace(hour=0, minute=0, second=0, microsecond=0)

    async with async_session() as session:
        q = select(
            Order.product_name,
            func.sum(Order.quantity).label("total_qty"),
            func.sum(Order.price).label("total_revenue")
        ).where(
            Order.timestamp >= start
        ).group_by(Order.product_name).order_by(text("total_revenue DESC")).limit(limit)

        result = await session.execute(q)
        rows = result.all()

    return {
        "products": [
            {
                "name": r.product_name,
                "quantity": int(r.total_qty),
                "revenue": float(r.total_revenue or 0)
            }
            for r in rows
        ]
    }


# ─────────────────────────────────────────────
# 5. Payment Status Breakdown
# ─────────────────────────────────────────────
@router.get("/payment-status")
async def get_payment_status(days: int = Query(default=30)):
    """Payment status distribution."""
    now = _now_local()
    start = now - timedelta(days=days) if days > 0 else now.replace(hour=0, minute=0, second=0, microsecond=0)

    async with async_session() as session:
        q = select(
            Order.payment_status,
            func.count(Order.id).label("count"),
            func.sum(Order.price).label("amount")
        ).where(Order.timestamp >= start).group_by(Order.payment_status)

        result = await session.execute(q)
        rows = result.all()

    return {
        "statuses": [
            {
                "status": r.payment_status.value if hasattr(r.payment_status, 'value') else str(r.payment_status),
                "count": int(r.count),
                "amount": float(r.amount or 0)
            }
            for r in rows
        ]
    }


# ─────────────────────────────────────────────
# 6. Moderator Performance
# ─────────────────────────────────────────────
@router.get("/moderators")
async def get_moderator_performance():
    """All moderators with their stats."""
    async with async_session() as session:
        stats = await analytics.get_all_moderators_stats(session)
    return {"moderators": stats}


# ─────────────────────────────────────────────
# 7. Stock Alerts
# ─────────────────────────────────────────────
@router.get("/stock-alerts")
async def get_stock_alerts():
    """Stock predictions for all products."""
    async with async_session() as session:
        predictions = await analytics.get_stock_predictions(session)
        all_products = await analytics.get_all_products(session)

    return {
        "predictions": predictions,
        "total_products": len(all_products)
    }


# ─────────────────────────────────────────────
# 8. Recent Orders (paginated)
# ─────────────────────────────────────────────
@router.get("/orders")
async def get_orders(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, le=100),
    platform: Optional[str] = Query(default=None),
    payment_status: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None)
):
    """Paginated orders with filters."""
    offset = (page - 1) * limit

    async with async_session() as session:
        conditions = []
        if platform:
            conditions.append(Order.platform == platform)
        if payment_status:
            conditions.append(Order.payment_status == payment_status)

        # Base query
        base = select(Order)
        count_q = select(func.count(Order.id))

        if search:
            from sqlalchemy import or_
            search_cond = or_(
                Order.product_name.ilike(f"%{search}%"),
                Order.phone_number.ilike(f"%{search}%"),
                Order.order_id.ilike(f"%{search}%")
            )
            conditions.append(search_cond)

        if conditions:
            base = base.where(and_(*conditions))
            count_q = count_q.where(and_(*conditions))

        # Total count
        total_result = await session.execute(count_q)
        total = total_result.scalar() or 0

        # Fetch page
        q = base.order_by(Order.timestamp.desc()).offset(offset).limit(limit)
        result = await session.execute(q)
        orders = result.scalars().all()

    return {
        "orders": [
            {
                "order_id": o.order_id,
                "product_name": o.product_name,
                "quantity": o.quantity,
                "price": float(o.price),
                "platform": o.platform.value if hasattr(o.platform, 'value') else str(o.platform),
                "payment_status": o.payment_status.value if hasattr(o.payment_status, 'value') else str(o.payment_status),
                "phone_number": o.phone_number or "—",
                "created_by_id": o.created_by_id or "—",
                "timestamp": o.timestamp.strftime("%Y-%m-%d %H:%M") if o.timestamp else "—"
            }
            for o in orders
        ],
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit if limit > 0 else 0
    }
