"""Access decision for the CIRA dashboard (pure functions, unit-tested).

Azure Container Apps built-in authentication (Entra ID) signs the user in before any request
reaches Streamlit and forwards the signed-in identity in the X-MS-CLIENT-PRINCIPAL-ID header.
The dashboard accepts that identity only when it equals the single allowed object ID
(CIRA_ALLOWED_PRINCIPAL_ID, set by Terraform). Anything else is denied (no access-key fallback).
"""
import hmac

PRINCIPAL_HEADER = "X-Ms-Client-Principal-Id"


def principal_from_headers(headers):
    """Return the forwarded Entra object ID (lower-case) or '' if absent."""
    if not headers:
        return ""
    value = headers.get(PRINCIPAL_HEADER) or headers.get(PRINCIPAL_HEADER.lower()) or ""
    return str(value).strip().lower()


def entra_allowed(headers, allowed_principal_id):
    """True only if a forwarded principal exists and matches the allowed object ID."""
    allowed = (allowed_principal_id or "").strip().lower()
    supplied = principal_from_headers(headers)
    if not allowed or not supplied:
        return False
    if not (allowed.isascii() and supplied.isascii()):
        return False
    return hmac.compare_digest(supplied, allowed)
