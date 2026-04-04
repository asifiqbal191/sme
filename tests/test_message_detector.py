"""
Tests for the Message Detection System.
Tests normalization, detection, and webhook payload processing.
"""

import pytest
from src.services.message_detector import (
    normalize_message_text,
    is_order_message,
)
from src.services.parser import parse_order_message


# ---------------------------------------------------------------------------
# Text Normalization Tests
# ---------------------------------------------------------------------------

class TestNormalizeMessageText:
    def test_basic_strip(self):
        assert normalize_message_text("  hello  ") == "hello"

    def test_collapse_multiple_spaces(self):
        assert normalize_message_text("Product:   Nike   Air   Max") == "Product: Nike Air Max"

    def test_normalize_line_endings(self):
        result = normalize_message_text("#ORDER\r\nProduct: Shoe\r\nQty: 1\r\nPrice: 100")
        assert "\r" not in result
        assert "#ORDER\nProduct: Shoe\nQty: 1\nPrice: 100" == result

    def test_remove_zero_width_chars(self):
        result = normalize_message_text("#ORDER\u200b\nProduct: Test")
        assert "\u200b" not in result

    def test_non_breaking_space(self):
        result = normalize_message_text("Product:\u00a0Nike")
        assert "\u00a0" not in result
        assert "Product: Nike" == result

    def test_empty_string(self):
        assert normalize_message_text("") == ""

    def test_none_input(self):
        assert normalize_message_text(None) == ""

    def test_preserves_newlines_structure(self):
        msg = "#ORDER\nProduct: Shoe\nQty: 2\nPrice: 500"
        result = normalize_message_text(msg)
        lines = result.split("\n")
        assert len(lines) == 4


# ---------------------------------------------------------------------------
# Order Detection Tests
# ---------------------------------------------------------------------------

class TestIsOrderMessage:
    def test_valid_order(self):
        assert is_order_message("#ORDER\nProduct: Test\nQty: 1\nPrice: 100") is True

    def test_case_insensitive(self):
        assert is_order_message("#order\nProduct: Test") is True
        assert is_order_message("#Order\nProduct: Test") is True
        assert is_order_message("#oRdEr\nProduct: Test") is True

    def test_not_order(self):
        assert is_order_message("Hello, how are you?") is False
        assert is_order_message("I want to order something") is False
        assert is_order_message("ORDER something") is False  # Missing #

    def test_empty(self):
        assert is_order_message("") is False
        assert is_order_message(None) is False

    def test_order_with_leading_space_after_normalize(self):
        normalized = normalize_message_text("   #ORDER\nProduct: Test")
        assert is_order_message(normalized) is True


# ---------------------------------------------------------------------------
# Parser Integration Tests
# ---------------------------------------------------------------------------

class TestParseIntegration:
    def test_full_order_parse(self):
        msg = normalize_message_text("""
            #ORDER
            ID: 123
            Product: Nike Air Max
            Qty: 2
            Price: 1500
        """)
        parsed = parse_order_message(msg)
        assert parsed is not None
        assert parsed.product_name == "Nike Air Max"
        assert parsed.quantity == 2
        assert parsed.price == 1500.0
        assert parsed.order_id == "123"

    def test_order_without_id(self):
        msg = normalize_message_text("#ORDER\nProduct: Shoe\nQty: 3\nPrice: 800")
        parsed = parse_order_message(msg)
        assert parsed is not None
        assert parsed.product_name == "Shoe"
        assert parsed.quantity == 3
        assert parsed.price == 800.0
        assert parsed.order_id is None

    def test_invalid_format_returns_none(self):
        msg = normalize_message_text("#ORDER\nThis is not a valid order")
        parsed = parse_order_message(msg)
        assert parsed is None

    def test_missing_qty_returns_none(self):
        msg = normalize_message_text("#ORDER\nProduct: Shoe\nPrice: 100")
        parsed = parse_order_message(msg)
        assert parsed is None

    def test_non_order_message_returns_none(self):
        parsed = parse_order_message("Hello there")
        assert parsed is None


# ---------------------------------------------------------------------------
# Webhook Payload Simulation Tests
# ---------------------------------------------------------------------------

class TestFacebookPayloadExtraction:
    """Test that correct text is extracted from Facebook payload structure."""

    def test_extract_text_from_facebook_payload(self):
        payload = {
            "entry": [{
                "messaging": [{
                    "sender": {"id": "12345"},
                    "message": {
                        "text": "#ORDER\nProduct: Test Item\nQty: 5\nPrice: 2500"
                    }
                }]
            }]
        }

        # Simulate extraction
        for entry in payload.get("entry", []):
            for event in entry.get("messaging", []):
                msg = event.get("message", {})
                text = msg.get("text", "")
                normalized = normalize_message_text(text)
                assert is_order_message(normalized)
                parsed = parse_order_message(normalized)
                assert parsed.product_name == "Test Item"
                assert parsed.quantity == 5
                assert parsed.price == 2500.0

    def test_non_order_facebook_message(self):
        payload = {
            "entry": [{
                "messaging": [{
                    "sender": {"id": "12345"},
                    "message": {"text": "Hey, what's the price of shoes?"}
                }]
            }]
        }

        for entry in payload.get("entry", []):
            for event in entry.get("messaging", []):
                text = event.get("message", {}).get("text", "")
                normalized = normalize_message_text(text)
                assert not is_order_message(normalized)


class TestWhatsAppPayloadExtraction:
    """Test that correct text is extracted from WhatsApp payload structure."""

    def test_extract_text_from_whatsapp_payload(self):
        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": "8801712345678",
                            "text": {
                                "body": "#ORDER\nProduct: Adidas Ultra Boost\nQty: 1\nPrice: 3200"
                            }
                        }]
                    }
                }]
            }]
        }

        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                messages = change.get("value", {}).get("messages", [])
                for m in messages:
                    text = m.get("text", {}).get("body", "")
                    phone = m.get("from", "")
                    normalized = normalize_message_text(text)
                    assert is_order_message(normalized)
                    parsed = parse_order_message(normalized)
                    assert parsed.product_name == "Adidas Ultra Boost"
                    assert parsed.quantity == 1
                    assert parsed.price == 3200.0
                    assert phone == "8801712345678"

    def test_non_order_whatsapp_message(self):
        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": "8801712345678",
                            "text": {"body": "Is this item available?"}
                        }]
                    }
                }]
            }]
        }

        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                messages = change.get("value", {}).get("messages", [])
                for m in messages:
                    text = m.get("text", {}).get("body", "")
                    normalized = normalize_message_text(text)
                    assert not is_order_message(normalized)


class TestEdgeCases:
    """Edge cases that should be handled gracefully."""

    def test_empty_payload_facebook(self):
        payload = {"entry": []}
        # Should not crash
        for entry in payload.get("entry", []):
            for event in entry.get("messaging", []):
                pass  # no-op

    def test_empty_payload_whatsapp(self):
        payload = {"entry": []}
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                pass

    def test_message_without_text_key(self):
        payload = {
            "entry": [{
                "messaging": [{
                    "sender": {"id": "123"},
                    "message": {"attachments": [{"type": "image"}]}
                }]
            }]
        }
        for entry in payload.get("entry", []):
            for event in entry.get("messaging", []):
                text = event.get("message", {}).get("text", "")
                assert text == ""
                assert not is_order_message(text)

    def test_whatsapp_formatted_order_with_extra_spaces(self):
        """WhatsApp sometimes adds extra formatting."""
        msg = normalize_message_text(
            "  #ORDER  \n  Product:   New Balance 990   \n  Qty:  3  \n  Price:  4500  "
        )
        assert is_order_message(msg)
        parsed = parse_order_message(msg)
        assert parsed is not None
        assert parsed.product_name == "New Balance 990"
        assert parsed.quantity == 3
        assert parsed.price == 4500.0
