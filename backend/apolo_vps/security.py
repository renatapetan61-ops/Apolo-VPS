from __future__ import annotations

import secrets
import string


def generate_password(length: int = 24) -> str:
    """Generate a high-entropy password without persisting or logging it."""
    if not 20 <= length <= 64:
        raise ValueError("Password length must be between 20 and 64 characters.")
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()-_=+"
    # Ensure complexity classes, then fill and securely shuffle.
    chars = [
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.digits),
        secrets.choice("!@#$%^&*()-_=+"),
    ]
    chars.extend(secrets.choice(alphabet) for _ in range(length - len(chars)))
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def generated_hostname(prefix: str = "apolo") -> str:
    suffix = secrets.token_hex(4)
    return f"{prefix}-{suffix}"
