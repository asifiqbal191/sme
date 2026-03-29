import asyncio
from datetime import datetime, timezone
import uuid
from src.db.session import engine, async_session
from src.db.models import Base, Product
from sqlalchemy import select

PRODUCTS_DATA = [
    {"name": "Nike Air Max", "stock": 50},       # High stock
    {"name": "Cotton T-Shirt V2", "stock": 3},   # Low stock
    {"name": "Leather Wallet Pro", "stock": 10},  # Moderate stock
    {"name": "Digital Watch X", "stock": 2},     # Very low stock
    {"name": "RayBan Aviator", "stock": 0}       # Out of stock
]

async def seed_products():
    print("Seeding products...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    async with async_session() as session:
        for p_data in PRODUCTS_DATA:
            # Check if product exists
            query = select(Product).where(Product.name == p_data["name"])
            result = await session.execute(query)
            existing = result.scalar_one_or_none()
            
            if existing:
                existing.current_stock = p_data["stock"]
                print(f"Updated {p_data['name']} stock to {p_data['stock']}")
            else:
                product = Product(
                    name=p_data["name"],
                    current_stock=p_data["stock"]
                )
                session.add(product)
                print(f"Created {p_data['name']} with stock {p_data['stock']}")
                
        await session.commit()
    print("Product seeding complete!")

if __name__ == "__main__":
    asyncio.run(seed_products())
