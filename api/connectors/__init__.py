"""
Connector registry.

Maps a connection `provider` to a pure parser ``(content: bytes, filename: str)
-> ParsedSocial``. Mirrors the pluggable-provider pattern in pipeline/contact.py:
adding a connector = add a parser module and one entry here.
"""
from api.connectors.meta import parse_meta

# provider -> parser(content: bytes, filename: str) -> ParsedSocial
PROVIDERS = {
    "meta_facebook": parse_meta,
    "meta_instagram": parse_meta,
    # "google_analytics": parse_ga,   # future
    # "gmail":            parse_gmail, # future
}

# provider -> human label + the lead_source tag imported rows would attribute to.
PROVIDER_LABELS = {
    "meta_facebook": "Facebook",
    "meta_instagram": "Instagram",
}
PROVIDER_LEAD_SOURCE = {
    "meta_facebook": "facebook",
    "meta_instagram": "instagram",
}


def is_supported(provider: str) -> bool:
    return provider in PROVIDERS


def get_parser(provider: str):
    return PROVIDERS.get(provider)
