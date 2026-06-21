"""Extract expense fields from a receipt photo using Claude vision.

A single stateless Messages API call with structured outputs. The image is held
in memory only for the duration of the call and never persisted (see the
scan-receipt endpoint). The app boots fine with no ANTHROPIC_API_KEY configured;
the key is checked lazily here so only the scan path fails when it's missing.
"""
import base64
import json
import logging

from api.models import EXPENSE_CATEGORIES
from config import ANTHROPIC_API_KEY, RECEIPT_SCAN_MODEL

log = logging.getLogger(__name__)

# Image MIME types the Claude vision API accepts.
SUPPORTED_MEDIA_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


class ReceiptExtractError(Exception):
    """Raised when extraction can't be performed or the model declined."""


# Built once on first use so importing this module never requires the SDK key.
_client = None


def _get_client():
    global _client
    if _client is None:
        if not ANTHROPIC_API_KEY:
            raise ReceiptExtractError(
                "Receipt scanning is not configured (ANTHROPIC_API_KEY is unset)."
            )
        import anthropic  # imported lazily so the app boots without the dependency wired
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


_SYSTEM = (
    "You extract structured expense data from a photo of a receipt for a "
    "service-business bookkeeping app. Return the grand total actually paid as "
    "`amount` (a positive number, no currency symbol). `vendor` is the merchant "
    "name. `expense_date` is the receipt's printed date in YYYY-MM-DD; if no date "
    "is legible, use today's date. Map the purchase to the single closest "
    "`category` from the allowed list — use 'other' when nothing fits. Set "
    "`is_tax_deductible` true for ordinary business purchases. Put a short "
    "human-readable note (e.g. key line items) in `description`. If a field "
    "genuinely can't be read, still return your best guess rather than failing."
)

# Strict schema — `category` is pinned to the same constant the create endpoint
# validates against, so the model can never return a category we'd reject.
_SCHEMA = {
    "type": "object",
    "properties": {
        "amount": {"type": "number"},
        "vendor": {"type": "string"},
        "expense_date": {"type": "string", "format": "date"},
        "category": {"type": "string", "enum": EXPENSE_CATEGORIES},
        "is_tax_deductible": {"type": "boolean"},
        "description": {"type": "string"},
    },
    "required": [
        "amount", "vendor", "expense_date", "category",
        "is_tax_deductible", "description",
    ],
    "additionalProperties": False,
}


def extract_receipt(image_bytes: bytes, media_type: str) -> dict:
    """Return a dict of extracted expense fields, or raise ReceiptExtractError."""
    if media_type not in SUPPORTED_MEDIA_TYPES:
        raise ReceiptExtractError(f"Unsupported image type: {media_type}")

    client = _get_client()
    b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    try:
        response = client.messages.create(
            model=RECEIPT_SCAN_MODEL,
            max_tokens=1024,
            system=_SYSTEM,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": b64},
                    },
                    {"type": "text", "text": "Extract the expense fields from this receipt."},
                ],
            }],
            output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
        )
    except Exception as e:  # network / SDK / auth errors
        log.warning("Receipt extraction call failed: %s", e)
        raise ReceiptExtractError("Could not read the receipt — please try again or enter it manually.")

    if response.stop_reason == "refusal":
        raise ReceiptExtractError("The image could not be processed as a receipt.")

    # output_config.format guarantees the first text block is schema-valid JSON.
    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        raise ReceiptExtractError("No data could be extracted from the image.")
    return json.loads(text)
