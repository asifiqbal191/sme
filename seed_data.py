import asyncio
from datetime import datetime, timedelta, timezone
import random
import uuid
from src.db.session import engine, async_session
from src.db.models import Base, Order, Payment, PlatformEnum, PaymentStatusEnum

PRODUCTS = ["Nike Air Max", "Cotton T-Shirt V2", "Leather Wallet Pro", "Digital Watch X", "RayBan Aviator"]
PHONES = ["+8801711122233", "+8801811122233", "+8801911122233", "+8801611122233"]

async def seed_database():
    print("Database seeding started...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    async with async_session() as session:
        # First, let's create some orders for the past 7 days
        now = datetime.now(timezone.utc)
        
        for i in range(20):
            # Random date within last 7 days
            days_ago = random.randint(0, 6)
            order_time = now - timedelta(days=days_ago, hours=random.randint(0, 10))
            
            product = random.choice(PRODUCTS)
            qty = random.randint(1, 3)
            price = round(random.uniform(500.0, 3000.0), 2)
            platform = random.choice(list(PlatformEnum))
            is_paid = random.choice([True, False])
            
            status = PaymentStatusEnum.PAID if is_paid else PaymentStatusEnum.PENDING
            sender_phone = random.choice(PHONES)
            
            order = Order(
                order_id=f"ORD-TEST-{str(uuid.uuid4())[:4].upper()}",
                product_name=product,
                quantity=qty,
                price=price,
                platform=platform,
                payment_status=status,
                phone_number=sender_phone,
                timestamp=order_time
            )
            session.add(order)
            await session.commit()
            
            if is_paid:
                payment = Payment(
                    sender_phone=sender_phone,
                    amount=price,  # matched perfectly
                    matched_order_id=order.id,
                    timestamp=order_time + timedelta(minutes=5)
                )
                session.add(payment)
                await session.commit()
                
        print("Inserted 20 simulated orders and corresponding payments successfully!")

if __name__ == "__main__":
    asyncio.run(seed_database())
