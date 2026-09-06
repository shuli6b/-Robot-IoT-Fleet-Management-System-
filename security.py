"""Server-side authentication and bounded, authenticated message envelopes."""
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from datetime import datetime, timedelta

SESSION_SECONDS = 12 * 3600
ITERATIONS = 600000
IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def password_hash(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), ITERATIONS).hex()
    return f"pbkdf2_sha256${ITERATIONS}${salt}${digest}"


def verify_password(password, stored):
    if not isinstance(stored, str):
        return False
    if stored.startswith("pbkdf2_sha256$"):
        try:
            _, rounds, salt, digest = stored.split("$")
            if not 100000 <= int(rounds) <= 2000000:
                return False
            actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds)).hex()
            return hmac.compare_digest(actual, digest)
        except (ValueError, TypeError):
            return False
    return hmac.compare_digest(hashlib.sha256(password.encode()).hexdigest(), stored)


def validate_password(password):
    if not isinstance(password, str) or not 12 <= len(password) <= 128:
        raise ValueError("密码须为12至128个字符")


def create_session(username, db_path):
    from database import get_connection
    token = secrets.token_urlsafe(48)
    now = int(time.time())
    with get_connection(db_path) as conn:
        conn.execute("DELETE FROM auth_sessions WHERE expires_at <= ?", (now,))
        conn.execute("INSERT INTO auth_sessions(token_hash, username, expires_at) VALUES(?,?,?)",
                     (hashlib.sha256(token.encode()).hexdigest(), username, now + SESSION_SECONDS))
    conn.close()
    return token


def session_user(token, db_path):
    from database import get_connection
    if not token or len(token) > 256:
        return None
    conn = get_connection(db_path)
    try:
        row = conn.execute("""SELECT u.id,u.username,u.role,u.real_name,u.status,u.created_at,u.last_login,
                       u.must_change_password FROM auth_sessions s JOIN users u ON u.username=s.username
                       WHERE s.token_hash=? AND s.expires_at>? AND u.status='approved'""",
                       (hashlib.sha256(token.encode()).hexdigest(), int(time.time()))).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def revoke_sessions(username, db_path):
    from database import get_connection
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute("DELETE FROM auth_sessions WHERE username=?", (username,))
    finally:
        conn.close()


def canonical_payload(payload):
    return json.dumps({k: v for k, v in payload.items() if k != "signature"},
                      ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sign_payload(payload, key):
    if not key:
        raise ValueError("Missing message signing key")
    result = dict(payload)
    result["signature"] = hmac.new(key.encode(), canonical_payload(result), hashlib.sha256).hexdigest()
    return result


def verify_payload(payload, key):
    if not isinstance(payload, dict) or not key:
        return False
    signature = payload.get("signature")
    if not isinstance(signature, str):
        return False
    try:
        expected = hmac.new(key.encode(), canonical_payload(payload), hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected)
    except (ValueError, TypeError):
        return False


def registered_devices():
    # Empty configuration fails closed; no device is trusted by its MQTT topic alone.
    return set(x.strip() for x in os.getenv("ROBOT_ALLOWED_DEVICES", "").split(",") if x.strip())


def allowed_device(device_type, device_id):
    return bool(IDENTIFIER.fullmatch(device_type) and IDENTIFIER.fullmatch(device_id)
                and f"{device_type}/{device_id}" in registered_devices())


def timestamp_age(value):
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        now = datetime.now(stamp.tzinfo) if stamp.tzinfo else datetime.now()
        return (now - stamp).total_seconds()
    except (ValueError, TypeError):
        return float("inf")

