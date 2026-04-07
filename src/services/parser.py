import re
from typing import Optional, Dict, Any
from pydantic import BaseModel, ValidationError

from src.db.models import PlatformEnum

class ParsedOrder(BaseModel):
    order_id: Optional[str] = None
    product_name: str
    quantity: int
    price: float
    payment_status: Optional[str] = "PENDING"
    platform: Optional[PlatformEnum] = None
    phone_number: Optional[str] = None

def parse_order_message(message_text: str) -> Optional[ParsedOrder]:
    """
    Parses a customer message looking for the `#ORDER` format.
    Expected format (example):
    #ORDER
    ID: 123 (Ignored)
    Product: Nike Air Max
    Qty: 2
    Price: 1500
    Status: PAID (Optional, defaults to PENDING)
    
    Can also detect platform overrides: #FB, #FACEBOOK, #WA, #WHATSAPP, #TG, #TELEGRAM
    """
    if not message_text:
        return None
    
    # Bypass invisible chars/stray spaces
    import re
    if not re.search(r'^[^#A-Z0-9]*#\s*ORDER', message_text.upper()):
        return None

    # Platform detection logic (look for hashtags)
    detected_platform = None
    if re.search(r'#(?:FB|FACEBOOK)', message_text, re.IGNORECASE):
        detected_platform = PlatformEnum.FACEBOOK
    elif re.search(r'#(?:WA|WHATSAPP)', message_text, re.IGNORECASE):
        detected_platform = PlatformEnum.WHATSAPP
    elif re.search(r'#(?:TG|TELEGRAM)', message_text, re.IGNORECASE):
        detected_platform = PlatformEnum.TELEGRAM

    # Case-insensitive Extraction logic
    id_match = re.search(r'ID:\s*([A-Z0-9\-]+)', message_text, re.IGNORECASE)
    product_match = re.search(r'Product:\s*(.+)', message_text, re.IGNORECASE)
    qty_match = re.search(r'(?:Qty|Quantity):\s*(\d+)', message_text, re.IGNORECASE)
    price_match = re.search(r'Price:\s*([\d\.]+)', message_text, re.IGNORECASE)
    status_match = re.search(r'Status:\s*([A-Z]+)', message_text, re.IGNORECASE)
    phone_match = re.search(r'Phone:\s*([\d\+\-\s]+)', message_text, re.IGNORECASE)

    if not (product_match and qty_match and price_match):
        return None
        
    try:
        product_name = product_match.group(1).strip().title()
        quantity = int(qty_match.group(1).strip())
        price = float(price_match.group(1).strip())
        
        payment_status = "PENDING"
        if status_match:
            status_val = status_match.group(1).strip().upper()
            if status_val == "PAID":
                payment_status = "PAID"
        
        return ParsedOrder(
            order_id=id_match.group(1).strip() if id_match else None,
            product_name=product_name,
            quantity=quantity,
            price=price,
            payment_status=payment_status,
            platform=detected_platform,
            phone_number=phone_match.group(1).strip() if phone_match else None
        )
    except (ValueError, ValidationError):
        return None
