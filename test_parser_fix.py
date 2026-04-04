
import asyncio
from src.services.parser import parse_order_message
from src.db.models import PlatformEnum

def test_parser():
    print("Testing Parser Platform Detection...")
    
    # Case 1: No platform tag
    m1 = "#ORDER\nProduct: Test1\nQty: 1\nPrice: 100"
    p1 = parse_order_message(m1)
    print(f"No tag: {p1.platform if p1 else 'Failed'}")
    
    # Case 2: FB tag
    m2 = "#ORDER #FB\nProduct: Test2\nQty: 1\nPrice: 100"
    p2 = parse_order_message(m2)
    print(f"FB tag: {p2.platform if p2 else 'Failed'}")
    
    # Case 3: WA tag (partial word)
    m3 = "#ORDER #WA\nProduct: Test3\nQty: 1\nPrice: 100"
    p3 = parse_order_message(m3)
    print(f"WA tag: {p3.platform if p3 else 'Failed'}")

    # Case 4: Full word WHATSAPP
    m4 = "#ORDER #WHATSAPP\nProduct: Test4\nQty: 1\nPrice: 100"
    p4 = parse_order_message(m4)
    print(f"WHATSAPP tag: {p4.platform if p4 else 'Failed'}")

if __name__ == "__main__":
    test_parser()
