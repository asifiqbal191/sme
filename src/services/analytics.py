from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text, and_
from datetime import datetime, timedelta, timezone
import pytz
from src.db.models import Order, PlatformEnum, Product
from typing import Optional

async def get_sales_for_range(session: AsyncSession, start_time: datetime, end_time: datetime, platform: Optional[PlatformEnum] = None):
    """
    Returns total sales amount and total orders for a given UTC time range.
    """
    conditions = [Order.timestamp >= start_time, Order.timestamp < end_time]
    if platform:
        conditions.append(Order.platform == platform)
    
    query = select(
        func.sum(Order.price * Order.quantity).label("total_sales"),
        func.count(Order.id).label("total_orders")
    ).where(and_(*conditions))
    
    result = await session.execute(query)
    row = result.first()
    
    return {
        "total_sales": float(row.total_sales or 0),
        "total_orders": int(row.total_orders or 0)
    }

async def get_daily_sales(session: AsyncSession, platform: Optional[PlatformEnum] = None):
    """
    Returns total sales amount and total orders for today (Asia/Dhaka time).
    """
    dhaka_tz = pytz.timezone("Asia/Dhaka")
    now_dhaka = datetime.now(dhaka_tz)
    
    # Start of today in Dhaka: 00:00:00
    start_of_day_dhaka = now_dhaka.replace(hour=0, minute=0, second=0, microsecond=0)
    # Convert to UTC for DB query
    start_of_day_utc = start_of_day_dhaka.astimezone(timezone.utc)
    
    return await get_sales_for_range(session, start_of_day_utc, datetime.now(timezone.utc), platform)

async def get_yesterday_sales(session: AsyncSession, platform: Optional[PlatformEnum] = None):
    """
    Returns total sales amount and total orders for yesterday (Asia/Dhaka time).
    """
    dhaka_tz = pytz.timezone("Asia/Dhaka")
    now_dhaka = datetime.now(dhaka_tz)
    
    # Yesterday in Dhaka
    yesterday_dhaka = now_dhaka - timedelta(days=1)
    start_of_yesterday_dhaka = yesterday_dhaka.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_yesterday_dhaka = start_of_yesterday_dhaka + timedelta(days=1)
    
    # Convert to UTC for DB query
    start_utc = start_of_yesterday_dhaka.astimezone(timezone.utc)
    end_utc = end_of_yesterday_dhaka.astimezone(timezone.utc)
    
    return await get_sales_for_range(session, start_utc, end_utc, platform)

async def get_weekly_top_product(session: AsyncSession):
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    query = select(
        Order.product_name,
        func.sum(Order.quantity).label("total_qty")
    ).where(
        Order.timestamp >= seven_days_ago
    ).group_by(
        Order.product_name
    ).order_by(
        text("total_qty DESC")
    ).limit(1)
    
    result = await session.execute(query)
    row = result.first()
    if row:
        return {"product_name": row.product_name, "quantity": row.total_qty}
    return None

async def get_today_top_product(session: AsyncSession):
    """Returns the top-selling product for today based on quantity sold, with its revenue."""
    dhaka_tz = pytz.timezone("Asia/Dhaka")
    now_dhaka = datetime.now(dhaka_tz)
    start_of_day_utc = now_dhaka.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)

    query = select(
        Order.product_name,
        func.sum(Order.quantity).label("total_qty"),
        func.sum(Order.price * Order.quantity).label("total_revenue")
    ).where(
        Order.timestamp >= start_of_day_utc
    ).group_by(
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

async def get_top_product(session: AsyncSession):
    """
    Returns the top-selling product for today based on quantity sold.
    Requirement: Use specific name get_top_product().
    """
    return await get_today_top_product(session)


async def get_weekly_sales(session: AsyncSession):
    """Returns total sales amount for the last 7 days."""
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)

    query = select(
        func.sum(Order.price * Order.quantity).label("total_sales"),
        func.count(Order.id).label("total_orders")
    ).where(Order.timestamp >= seven_days_ago)

    result = await session.execute(query)
    row = result.first()
    return {
        "total_sales": row.total_sales or 0,
        "total_orders": row.total_orders or 0
    }


async def get_monthly_sales(session: AsyncSession):
    """Returns total sales amount for the last 30 days."""
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)

    query = select(
        func.sum(Order.price * Order.quantity).label("total_sales"),
        func.count(Order.id).label("total_orders")
    ).where(Order.timestamp >= thirty_days_ago)

    result = await session.execute(query)
    row = result.first()
    return {
        "total_sales": row.total_sales or 0,
        "total_orders": row.total_orders or 0
    }


async def get_monthly_top_product(session: AsyncSession):
    """Returns the top-selling product for the last 30 days."""
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    query = select(
        Order.product_name,
        func.sum(Order.quantity).label("total_qty")
    ).where(
        Order.timestamp >= thirty_days_ago
    ).group_by(
        Order.product_name
    ).order_by(
        text("total_qty DESC")
    ).limit(1)

    result = await session.execute(query)
    row = result.first()
    if row:
        return {"product_name": row.product_name, "quantity": row.total_qty}
    return None


async def get_recent_orders(session: AsyncSession, limit: int = 10, platform: Optional[PlatformEnum] = None):
    conditions = []
    if platform:
        conditions.append(Order.platform == platform)
        
    query = select(Order)
    if conditions:
        query = query.where(and_(*conditions))
        
    query = query.order_by(Order.timestamp.desc()).limit(limit)
    result = await session.execute(query)
    return result.scalars().all()

async def get_pending_orders(session: AsyncSession, limit: int = 10, platform: Optional[PlatformEnum] = None):
    conditions = [Order.payment_status == 'PENDING']
    if platform:
        conditions.append(Order.platform == platform)
        
    query = select(Order).where(and_(*conditions)).order_by(Order.timestamp.desc()).limit(limit)
    result = await session.execute(query)
    return result.scalars().all()

async def get_stock_predictions(session: AsyncSession, lookback_days: int = 30):
    """
    Predicts when products will run out based on sales trends.
    Calculates average daily sales and days remaining.
    """
    # 1. Fetch all products
    products_query = select(Product)
    products_result = await session.execute(products_query)
    products = products_result.scalars().all()
    
    if not products:
        return []
    
    # 2. Calculate average daily sales for each product over lookback period
    start_date = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    
    sales_query = select(
        Order.product_name,
        func.sum(Order.quantity).label("total_qty")
    ).where(
        Order.timestamp >= start_date
    ).group_by(
        Order.product_name
    )
    
    sales_result = await session.execute(sales_query)
    sales_data = {row.product_name: float(row.total_qty) for row in sales_result}
    
    predictions = []
    for p in products:
        total_sold = sales_data.get(p.name, 0)
        avg_daily_sales = total_sold / lookback_days
        
        if avg_daily_sales > 0:
            days_remaining = p.current_stock / avg_daily_sales
        else:
            # If no sales in lookback period, but has stock, it's not "running out"
            days_remaining = 999  # Large number instead of inf for easier formatting
            
        predictions.append({
            "product_name": p.name,
            "current_stock": p.current_stock,
            "avg_daily_sales": avg_daily_sales,
            "days_remaining": days_remaining
        })
        
    return predictions

async def get_revenue_breakdown(session: AsyncSession, start_time: datetime, end_time: datetime, limit: int = 3):
    """
    Returns the top products by revenue (price * quantity) for a given UTC time range.
    """
    query = select(
        Order.product_name,
        func.sum(Order.price * Order.quantity).label("total_revenue")
    ).where(
        Order.timestamp >= start_time,
        Order.timestamp < end_time
    ).group_by(
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
