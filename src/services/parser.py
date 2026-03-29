import re
from typing import Optional, Dict, Any
from pydantic import BaseModel, ValidationError

class ParsedOrder(BaseModel):
    order_id: Optional[str] = None
    product_name: str
    quantity: int
    price: float

def parse_order_message(message_text: str) -> Optional[ParsedOrder]:
    """
    Parses a customer message looking for the `#ORDER` format.
    Expected format (example):
    #ORDER
    ID: 123 (Ignored)
    Product: Nike Air Max
    Qty: 2
    Price: 1500
    """
    if not message_text or not message_text.strip().upper().startswith("#ORDER"):
        return None

    # Case-insensitive Extraction logic
    id_match = re.search(r'ID:\s*([A-Z0-9\-]+)', message_text, re.IGNORECASE)
    product_match = re.search(r'Product:\s*(.+)', message_text, re.IGNORECASE)
    qty_match = re.search(r'Qty:\s*(\d+)', message_text, re.IGNORECASE)
    price_match = re.search(r'Price:\s*([\d\.]+)', message_text, re.IGNORECASE)

    if not (product_match and qty_match and price_match):
        return None
        
    try:
        product_name = product_match.group(1).strip()
        quantity = int(qty_match.group(1).strip())
        price = float(price_match.group(1).strip())
        
        return ParsedOrder(
            order_id=id_match.group(1).strip() if id_match else None,
            product_name=product_name,
            quantity=quantity,
            price=price
        )
    except (ValueError, ValidationError):
        return None
