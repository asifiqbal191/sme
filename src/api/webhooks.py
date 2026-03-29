from fastapi import APIRouter, Depends, Query, BackgroundTasks, Request, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.session import get_db
from src.db.models import Order, PlatformEnum
from src.services.parser import parse_order_message
from src.services.sheets import push_to_google_sheets
from src.services.payment import match_payment
from src.core.config import settings
import uuid
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook")

def _generate_order_id():
    # Simple ID generator: ORD-UUID-short
    return f"ORD-{str(uuid.uuid4())[:8].upper()}"

# --- FACEBOOK WEBHOOK --- #
@router.get("/facebook")
async def verify_facebook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token")
):
    """ Facebook Webhook Verification Endpoints """
    if hub_mode == "subscribe" and hub_verify_token == settings.FACEBOOK_VERIFY_TOKEN:
        return int(hub_challenge)
    raise HTTPException(status_code=403, detail="Verification failed")

@router.post("/facebook")
async def receive_facebook(request: Request, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    """ Facebook Messenger Incoming Messages """
    payload = await request.json()
    
    # Facebook Graph API Structure
    for entry in payload.get("entry", []):
        for messaging_event in entry.get("messaging", []):
            message = messaging_event.get("message")
            if message and message.get("text"):
                text = message.get("text")
                parsed = parse_order_message(text)
                
                if parsed:
                    # Insert Order
                    new_order = Order(
                        order_id=_generate_order_id(),
                        product_name=parsed.product_name,
                        quantity=parsed.quantity,
                        price=parsed.price,
                        platform=PlatformEnum.FACEBOOK
                    )
                    db.add(new_order)
                    await db.commit()
                    await db.refresh(new_order)
                    
                    # Schedule Google Sheet Push
                    order_dict = {
                        "id": new_order.id,
                        "order_id": new_order.order_id,
                        "product_name": new_order.product_name,
                        "quantity": new_order.quantity,
                        "price": new_order.price,
                        "platform": new_order.platform.value,
                        "timestamp": new_order.timestamp.isoformat(),
                        "payment_status": new_order.payment_status.value,
                        "phone_number": ""
                    }
                    background_tasks.add_task(push_to_google_sheets, order_dict)
                    
                    logger.info(f"New Facebook order created: {new_order.order_id}")
                    # In a real scenario, you can reply directly to Facebook user here
                        
                    return {"status": "success"}

    return {"status": "ok"}


# --- WHATSAPP WEBHOOK --- #
@router.get("/whatsapp")
async def verify_whatsapp(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token")
):
    if hub_mode == "subscribe" and hub_verify_token == settings.WHATSAPP_VERIFY_TOKEN:
        return int(hub_challenge)
    raise HTTPException(status_code=403, detail="Verification failed")

@router.post("/whatsapp")
async def receive_whatsapp(request: Request, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    """ WhatsApp Business API Incoming Messages """
    payload = await request.json()
    
    # Standard WhatsApp Business API Structure
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("value", {}).get("messages"):
                for m in change["value"]["messages"]:
                    text = m.get("text", {}).get("body", "")
                    sender_phone = m.get("from", "")
                    
                    parsed = parse_order_message(text)
                    if parsed:
                        new_order = Order(
                            order_id=_generate_order_id(),
                            product_name=parsed.product_name,
                            quantity=parsed.quantity,
                            price=parsed.price,
                            platform=PlatformEnum.WHATSAPP,
                            phone_number=sender_phone # Helpful for payment
                        )
                        db.add(new_order)
                        await db.commit()
                        await db.refresh(new_order)
                        
                        # Background push
                        order_dict = {
                            "id": new_order.id, "order_id": new_order.order_id,
                            "product_name": new_order.product_name, "quantity": new_order.quantity,
                            "price": new_order.price, "platform": new_order.platform.value,
                            "timestamp": new_order.timestamp.isoformat(),
                            "payment_status": new_order.payment_status.value,
                            "phone_number": sender_phone
                        }
                        background_tasks.add_task(push_to_google_sheets, order_dict)
                        
                        logger.info(f"New WhatsApp order created: {new_order.order_id}")

    return {"status": "ok"}

# --- SMS Webhook (Payment Integration) --- #
from typing import Optional
from pydantic import BaseModel

class SMSPayload(BaseModel):
    phone_number: str
    message: str
    amount: float
    timestamp: Optional[str] = None

@router.post("/sms")
async def receive_sms(payload: SMSPayload, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    """
    Receives SMS forwarded via an Android app or SMS reading API.
    Attempts to match payment using amount & sender number.
    """
    matched = await match_payment(db, amount=payload.amount, sender_phone=payload.phone_number)
    if matched:
        return {"status": "Payment matched and order updated"}
    return {"status": "Payment received, but no matching unfulfilled order found"}
