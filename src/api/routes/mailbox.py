"""Private mailbox system for trusted API key holders."""

import grp
import hashlib
import json
import os
import re
import secrets
import shutil
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import bcrypt
import structlog
from fastapi import APIRouter, Header, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator

from api.services.attachments import (
    get_attachment_path,
    get_mime_type,
    sanitize_image,
    store_attachment,
    validate_image,
)
from api.services.moderator import log_moderation, moderate_message, screen_injection

logger = structlog.get_logger()

router = APIRouter(prefix="/mailbox", tags=["mailbox"])

MAILBOX_DIR = Path("/claude-home/mailbox")
ACCOUNTS_FILE = Path("/claude-home/data/mailbox-accounts.json")
RATE_LIMIT_FILE = Path("/claude-home/data/api-rate-limits.json")

BCRYPT_COST = 12
SESSION_TTL_DAYS = 7
SESSION_TTL_SECONDS = SESSION_TTL_DAYS * 86400
MAX_WORDS = 1500
COOLDOWN_MINUTES = 15
DAILY_MESSAGE_CAP = 10
CLAUDE_GROUP = "claude"

USERNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,18}[a-z0-9]$")
LOGIN_MAX_FAILURES = 5
LOGIN_WINDOW_SECONDS = 900

_login_failures: dict[str, list[float]] = {}


# --- Filesystem helpers ---


def _set_claude_group(path: Path) -> None:
    """Set ownership to root:claude with group write."""
    try:
        gid = grp.getgrnam(CLAUDE_GROUP).gr_gid
        shutil.chown(str(path), user="root", group=gid)
        path.chmod(0o664 if path.is_file() else 0o775)
    except (KeyError, OSError):
        pass


# --- Account storage ---


AccountData = dict[str, str | dict[str, dict[str, str]]]
AccountStore = dict[str, AccountData]


def load_accounts() -> AccountStore:
    """Load mailbox accounts from disk."""
    if not ACCOUNTS_FILE.exists():
        return {}
    try:
        raw: object = json.loads(ACCOUNTS_FILE.read_text())
        if isinstance(raw, dict):
            return raw
        return {}
    except (json.JSONDecodeError, OSError):
        logger.error("mailbox_accounts_load_failed")
        return {}


def save_accounts(accounts: AccountStore) -> None:
    """Atomically write accounts to disk."""
    ACCOUNTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = ACCOUNTS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(accounts, indent=2))
    tmp.replace(ACCOUNTS_FILE)


def get_trusted_keys() -> set[str]:
    """Load trusted API keys from environment."""
    raw = os.getenv("TRUSTED_API_KEYS", "")
    return {k.strip() for k in raw.split(",") if k.strip()}


def find_account_by_username(
    accounts: AccountStore, username: str
) -> tuple[str, AccountData] | None:
    """Find account by username, returning (api_key, account_data)."""
    for api_key, acct in accounts.items():
        if acct.get("username") == username:
            return api_key, acct
    return None


def find_account_by_session(
    accounts: AccountStore, token: str
) -> tuple[str, AccountData] | None:
    """Find account by session token, returning (api_key, account_data)."""
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    now = datetime.now(UTC).isoformat()
    for api_key, acct in accounts.items():
        sessions = acct.get("sessions", {})
        if isinstance(sessions, dict):
            sess = sessions.get(token_hash)
            if isinstance(sess, dict) and sess.get("expires", "") > now:
                return api_key, acct
    return None


# --- Session auth helper ---


def require_session(
    accounts: AccountStore, authorization: str
) -> tuple[str, AccountData]:
    """Validate session token from Authorization header.

    Args:
        accounts: Loaded account store.
        authorization: Raw Authorization header value.

    Returns:
        Tuple of (api_key, account_data).

    Raises:
        HTTPException: If the session token is invalid or expired.
    """
    token = authorization.removeprefix("Bearer ").strip()
    if not token.startswith("ses_"):
        raise HTTPException(status_code=401, detail="Invalid session token")
    result = find_account_by_session(accounts, token)
    if result is None:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return result


# --- Login rate limiting ---


def check_login_rate_limit(ip: str) -> None:
    """Check and enforce login rate limit per IP.

    Args:
        ip: Client IP address.

    Raises:
        HTTPException: If rate limit is exceeded.
    """
    now = time.monotonic()
    attempts = _login_failures.get(ip, [])
    cutoff = now - LOGIN_WINDOW_SECONDS
    recent = [t for t in attempts if t > cutoff]
    _login_failures[ip] = recent
    if len(recent) >= LOGIN_MAX_FAILURES:
        logger.warning("mailbox_login_rate_limited", ip=ip, attempt_count=len(recent))
        raise HTTPException(
            status_code=429,
            detail="Too many failed login attempts. Try again later.",
        )


def record_login_failure(ip: str) -> None:
    """Record a failed login attempt."""
    now = time.monotonic()
    if ip not in _login_failures:
        _login_failures[ip] = []
    _login_failures[ip].append(now)


# --- JSONL helpers ---


MessageDict = dict[str, object]


def read_thread(username: str) -> list[MessageDict]:
    """Read all messages from a user's thread, skipping corrupt lines.

    Args:
        username: Mailbox account username.

    Returns:
        List of parsed message dictionaries.
    """
    thread_path = MAILBOX_DIR / username / "thread.jsonl"
    if not thread_path.exists():
        return []
    messages: list[MessageDict] = []
    for line_num, line in enumerate(thread_path.read_text().splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            parsed: object = json.loads(stripped)
            if isinstance(parsed, dict):
                messages.append(parsed)
        except json.JSONDecodeError:
            logger.warning(
                "mailbox_jsonl_corrupt_line",
                username=username,
                line_number=line_num,
            )
    return messages


def append_to_thread(username: str, message: MessageDict) -> None:
    """Append a message to a user's thread.jsonl.

    Args:
        username: Mailbox account username.
        message: Message dictionary to append.
    """
    thread_dir = MAILBOX_DIR / username
    thread_dir.mkdir(parents=True, exist_ok=True)
    _set_claude_group(thread_dir)
    thread_path = thread_dir / "thread.jsonl"
    line = json.dumps(message, separators=(",", ":")) + "\n"
    with thread_path.open("a") as f:
        f.write(line)
    _set_claude_group(thread_path)


def read_cursor(username: str) -> str | None:
    """Read the user's read cursor.

    Args:
        username: Mailbox account username.

    Returns:
        Last read message ID, or None if no cursor exists.
    """
    cursor_path = MAILBOX_DIR / username / "cursor.json"
    if not cursor_path.exists():
        return None
    try:
        data: object = json.loads(cursor_path.read_text())
        if isinstance(data, dict):
            val = data.get("last_read_id")
            return str(val) if val is not None else None
        return None
    except (json.JSONDecodeError, OSError):
        return None


def write_cursor(username: str, last_read_id: str) -> None:
    """Atomically write the user's read cursor.

    Args:
        username: Mailbox account username.
        last_read_id: Message ID to set as cursor.
    """
    cursor_dir = MAILBOX_DIR / username
    cursor_dir.mkdir(parents=True, exist_ok=True)
    cursor_path = cursor_dir / "cursor.json"
    tmp = cursor_path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"last_read_id": last_read_id}))
    tmp.replace(cursor_path)
    _set_claude_group(cursor_path)


def generate_message_id(username: str, prefix: str) -> str:
    """Generate a message ID with date and sequence number.

    Args:
        username: The mailbox owner.
        prefix: 'u' for user messages, 'c' for claudie messages.

    Returns:
        Message ID in format msg_YYYYMMDD_<prefix>_NNN.
    """
    today = datetime.now(UTC).strftime("%Y%m%d")
    id_prefix = f"msg_{today}_{prefix}_"
    messages = read_thread(username)
    count = sum(
        1
        for m in messages
        if isinstance(m.get("id"), str) and str(m["id"]).startswith(id_prefix)
    )
    return f"{id_prefix}{count + 1:03d}"


def _msg_ts(msg: MessageDict) -> str:
    """Extract timestamp string from a message dict."""
    ts = msg.get("ts", "")
    return str(ts) if ts is not None else ""


def _msg_id(msg: MessageDict) -> str:
    """Extract ID string from a message dict."""
    mid = msg.get("id", "")
    return str(mid) if mid is not None else ""


def _msg_from(msg: MessageDict) -> str:
    """Extract sender string from a message dict."""
    sender = msg.get("from", "")
    return str(sender) if sender is not None else ""


def compute_unread(messages: list[MessageDict], cursor_id: str | None) -> int:
    """Count unread claudie messages after the cursor.

    Args:
        messages: All thread messages.
        cursor_id: Current read cursor message ID.

    Returns:
        Number of unread messages from claudie.
    """
    if cursor_id is None:
        return sum(1 for m in messages if _msg_from(m) == "claudie")
    past_cursor = False
    unread = 0
    for msg in sorted(messages, key=_msg_ts):
        if _msg_id(msg) == cursor_id:
            past_cursor = True
            continue
        if past_cursor and _msg_from(msg) == "claudie":
            unread += 1
    return unread


# --- Rate limiting ---


def load_rate_limits() -> dict[str, list[str]]:
    """Load rate limit timestamp lists from file."""
    if not RATE_LIMIT_FILE.exists():
        return {}
    try:
        raw: object = json.loads(RATE_LIMIT_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(raw, dict):
        return {}
    migrated: dict[str, list[str]] = {}
    for key, value in raw.items():
        if isinstance(value, str):
            migrated[key] = [value]
        elif isinstance(value, list):
            migrated[key] = [str(v) for v in value]
        else:
            migrated[key] = []
    return migrated


def save_rate_limits(limits: dict[str, list[str]]) -> None:
    """Save rate limit timestamp lists to file."""
    RATE_LIMIT_FILE.parent.mkdir(parents=True, exist_ok=True)
    RATE_LIMIT_FILE.write_text(json.dumps(limits, indent=2))


def _safe_parse_iso(ts: str) -> datetime | None:
    """Parse ISO timestamp, returning None on failure."""
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def check_message_rate_limit(api_key: str) -> tuple[bool, str | None]:
    """Check cooldown and daily cap for a message sender.

    Args:
        api_key: Sender's API key.

    Returns:
        Tuple of (allowed, reason). reason is None when allowed.
    """
    limits = load_rate_limits()
    timestamps = limits.get(api_key, [])
    if not timestamps:
        return True, None
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        last_time = datetime.fromisoformat(timestamps[-1])
    except ValueError:
        return True, None
    cooldown_end = last_time + timedelta(minutes=COOLDOWN_MINUTES)
    if now < cooldown_end:
        remaining = int((cooldown_end - now).total_seconds())
        minutes = remaining // 60
        seconds = remaining % 60
        return False, f"Cooldown active. Try again in {minutes}m {seconds}s"
    today_count = 0
    for ts in timestamps:
        parsed_ts = _safe_parse_iso(ts)
        if parsed_ts is not None and parsed_ts >= today_start:
            today_count += 1
    if today_count >= DAILY_MESSAGE_CAP:
        return (
            False,
            f"Daily limit of {DAILY_MESSAGE_CAP} messages reached. Resets at midnight.",
        )
    return True, None


def record_message_usage(api_key: str) -> None:
    """Record a message send timestamp.

    Args:
        api_key: Sender's API key.
    """
    limits = load_rate_limits()
    timestamps = limits.get(api_key, [])
    now = datetime.now()
    cutoff = now - timedelta(hours=24)
    pruned = [
        ts
        for ts in timestamps
        if (parsed := _safe_parse_iso(ts)) is not None and parsed >= cutoff
    ]
    pruned.append(now.isoformat())
    limits[api_key] = pruned
    save_rate_limits(limits)


# --- Request/Response models ---


class RegisterRequest(BaseModel):
    """Registration request body."""

    username: str = Field(..., min_length=2, max_length=20)
    display_name: str = Field(..., min_length=1, max_length=50)

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        """Enforce lowercase alphanumeric + hyphens."""
        if not USERNAME_PATTERN.match(v):
            msg = "Username must be 2-20 lowercase alphanumeric characters or hyphens"
            raise ValueError(msg)
        return v


class RegisterResponse(BaseModel):
    """Registration response."""

    username: str
    display_name: str
    web_password: str


class ResetPasswordResponse(BaseModel):
    """Password reset response."""

    username: str
    web_password: str


class LoginRequest(BaseModel):
    """Login request body."""

    password: str = Field(..., min_length=1)


class LoginResponse(BaseModel):
    """Login response."""

    session_token: str
    expires_in: int
    username: str
    display_name: str


class StatusResponse(BaseModel):
    """Mailbox status response."""

    username: str
    unread: int
    total: int
    display_name: str
    last_message: str | None


class ThreadResponse(BaseModel):
    """Thread listing response."""

    messages: list[MessageDict]
    has_more: bool


class ReadRequest(BaseModel):
    """Read cursor advance request."""

    last_read_id: str = Field(..., min_length=1)


class ReadResponse(BaseModel):
    """Read cursor response."""

    last_read_id: str


class SendRequest(BaseModel):
    """Send message request."""

    message: str = Field(..., min_length=1)


class AttachmentInfo(BaseModel):
    """Attachment metadata in thread messages."""

    filename: str
    mime: str
    size: int


class SendResponse(BaseModel):
    """Send message response."""

    id: str
    word_count: int
    attachment: AttachmentInfo | None = None


# --- Endpoints ---


@router.post("/register", response_model=RegisterResponse)
async def register(
    body: RegisterRequest,
    authorization: str = Header(..., description="Bearer API key"),
) -> RegisterResponse:
    """Register a trusted API key holder for web mailbox access."""
    token = authorization.removeprefix("Bearer ").strip()
    trusted_keys = get_trusted_keys()

    if token not in trusted_keys:
        logger.warning(
            "mailbox_register_invalid_key",
            token_prefix=token[:8] if token else "",
        )
        raise HTTPException(status_code=401, detail="Invalid API key")

    accounts = load_accounts()

    if token in accounts:
        raise HTTPException(status_code=409, detail="API key already registered")

    existing = find_account_by_username(accounts, body.username)
    if existing is not None:
        raise HTTPException(status_code=409, detail="Username already taken")

    password_raw = f"mb_{body.username}_{secrets.token_hex(16)}"
    password_hash = bcrypt.hashpw(
        password_raw.encode()[:72], bcrypt.gensalt(rounds=BCRYPT_COST)
    ).decode()

    accounts[token] = {
        "username": body.username,
        "display_name": body.display_name,
        "web_password_hash": password_hash,
        "registered": datetime.now(UTC).isoformat(),
        "sessions": {},
    }
    save_accounts(accounts)

    user_dir = MAILBOX_DIR / body.username
    user_dir.mkdir(parents=True, exist_ok=True)
    _set_claude_group(user_dir)

    logger.info(
        "mailbox_register",
        username=body.username,
        key_prefix=token[:8],
    )

    return RegisterResponse(
        username=body.username,
        display_name=body.display_name,
        web_password=password_raw,
    )


@router.post("/reset-password", response_model=ResetPasswordResponse)
async def reset_password(
    authorization: str = Header(..., description="Bearer API key"),
) -> ResetPasswordResponse:
    """Generate a new web password, invalidating the old one."""
    token = authorization.removeprefix("Bearer ").strip()
    trusted_keys = get_trusted_keys()

    if token not in trusted_keys:
        raise HTTPException(status_code=401, detail="Invalid API key")

    accounts = load_accounts()
    acct = accounts.get(token)
    if acct is None:
        raise HTTPException(status_code=404, detail="Not registered for mailbox")

    username = str(acct.get("username", ""))
    password_raw = f"mb_{username}_{secrets.token_hex(16)}"
    password_hash = bcrypt.hashpw(
        password_raw.encode()[:72], bcrypt.gensalt(rounds=BCRYPT_COST)
    ).decode()

    acct["web_password_hash"] = password_hash
    acct["sessions"] = {}
    save_accounts(accounts)

    logger.info("mailbox_password_reset", username=username)

    return ResetPasswordResponse(username=username, web_password=password_raw)


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, request: Request) -> LoginResponse:
    """Exchange web password for a session token."""
    ip = request.client.host if request.client else "unknown"
    check_login_rate_limit(ip)

    accounts = load_accounts()

    matched_key: str | None = None
    matched_acct: AccountData | None = None

    for api_key, acct in accounts.items():
        stored_hash = acct.get("web_password_hash", "")
        if (
            isinstance(stored_hash, str)
            and stored_hash
            and bcrypt.checkpw(body.password.encode()[:72], stored_hash.encode())
        ):
            matched_key = api_key
            matched_acct = acct
            break

    if matched_key is None or matched_acct is None:
        record_login_failure(ip)
        logger.warning(
            "mailbox_login_failed",
            reason="invalid_password",
            ip=ip,
        )
        raise HTTPException(status_code=401, detail="Invalid password")

    session_token = f"ses_{secrets.token_hex(32)}"
    token_hash = hashlib.sha256(session_token.encode()).hexdigest()
    expires = datetime.now(UTC) + timedelta(days=SESSION_TTL_DAYS)

    now_iso = datetime.now(UTC).isoformat()
    sessions = matched_acct.get("sessions", {})
    if isinstance(sessions, dict):
        matched_acct["sessions"] = {
            k: v
            for k, v in sessions.items()
            if isinstance(v, dict) and v.get("expires", "") > now_iso
        }
    else:
        matched_acct["sessions"] = {}

    sessions_dict = matched_acct["sessions"]
    if isinstance(sessions_dict, dict):
        sessions_dict[token_hash] = {"expires": expires.isoformat()}
    save_accounts(accounts)

    username = str(matched_acct.get("username", ""))
    display_name = str(matched_acct.get("display_name", username))

    logger.info("mailbox_login", username=username)

    return LoginResponse(
        session_token=session_token,
        expires_in=SESSION_TTL_SECONDS,
        username=username,
        display_name=display_name,
    )


@router.get("/status", response_model=StatusResponse)
async def status(
    authorization: str = Header(..., description="Bearer session token"),
) -> StatusResponse:
    """Quick unread check for the authenticated user."""
    accounts = load_accounts()
    _, acct = require_session(accounts, authorization)

    username = str(acct.get("username", ""))
    display_name = str(acct.get("display_name", username))
    messages = read_thread(username)
    cursor_id = read_cursor(username)
    unread = compute_unread(messages, cursor_id)

    last_msg_ts: str | None = None
    if messages:
        sorted_msgs = sorted(messages, key=_msg_ts)
        last_msg_ts = _msg_ts(sorted_msgs[-1]) or None

    return StatusResponse(
        username=username,
        unread=unread,
        total=len(messages),
        display_name=display_name,
        last_message=last_msg_ts,
    )


def _get_cursor_ts(sorted_msgs: list[MessageDict], cursor_id: str) -> str:
    """Get the timestamp of the cursor message."""
    for msg in sorted_msgs:
        if _msg_id(msg) == cursor_id:
            return _msg_ts(msg)
    return ""


@router.get("/thread", response_model=ThreadResponse)
async def thread(
    authorization: str = Header(..., description="Bearer session token"),
    limit: int = 50,
    before: str | None = None,
) -> ThreadResponse:
    """Full conversation thread, paginated. Auto-advances read cursor."""
    accounts = load_accounts()
    _, acct = require_session(accounts, authorization)

    username = str(acct.get("username", ""))
    all_messages = read_thread(username)
    sorted_msgs = sorted(all_messages, key=_msg_ts)

    cursor_id = read_cursor(username)

    if before is not None:
        cut_idx = next(
            (i for i, m in enumerate(sorted_msgs) if _msg_id(m) == before),
            len(sorted_msgs),
        )
        sorted_msgs = sorted_msgs[:cut_idx]

    has_more = len(sorted_msgs) > limit
    page = sorted_msgs[-limit:] if has_more else sorted_msgs

    for msg in page:
        if _msg_from(msg) == "claudie":
            if cursor_id is None:
                msg["status"] = "unread"
            else:
                msg_ts = _msg_ts(msg)
                cursor_ts = _get_cursor_ts(sorted_msgs, cursor_id)
                msg["status"] = "unread" if msg_ts > cursor_ts else "read"
        else:
            msg["status"] = "read"

    if page:
        last_id = _msg_id(page[-1])
        if last_id and last_id != cursor_id:
            should_advance = cursor_id is None
            if not should_advance and cursor_id is not None:
                last_ts = _msg_ts(page[-1])
                cursor_ts = _get_cursor_ts(sorted_msgs, cursor_id)
                should_advance = last_ts > cursor_ts
            if should_advance:
                write_cursor(username, last_id)

    return ThreadResponse(messages=page, has_more=has_more)


@router.patch("/read", response_model=ReadResponse)
async def mark_read(
    body: ReadRequest,
    authorization: str = Header(..., description="Bearer session token"),
) -> ReadResponse:
    """Advance the user's read cursor."""
    accounts = load_accounts()
    _, acct = require_session(accounts, authorization)

    username = str(acct.get("username", ""))
    messages = read_thread(username)

    msg_exists = any(_msg_id(m) == body.last_read_id for m in messages)
    if not msg_exists:
        raise HTTPException(status_code=400, detail="Invalid message ID")

    current_cursor = read_cursor(username)
    if current_cursor is not None:
        current_ts = ""
        new_ts = ""
        for msg in messages:
            if _msg_id(msg) == current_cursor:
                current_ts = _msg_ts(msg)
            if _msg_id(msg) == body.last_read_id:
                new_ts = _msg_ts(msg)
        if new_ts <= current_ts:
            return ReadResponse(last_read_id=current_cursor)

    write_cursor(username, body.last_read_id)

    return ReadResponse(last_read_id=body.last_read_id)


@router.post("/send", response_model=SendResponse)
async def send(
    request: Request,
    authorization: str = Header(..., description="Bearer session token"),
) -> SendResponse:
    """Send a message to Claudie, optionally with an image attachment.

    Accepts JSON (text-only) or multipart/form-data (text + image).
    """
    content_type = request.headers.get("content-type", "")
    message = ""
    image: UploadFile | None = None

    if "multipart/form-data" in content_type:
        form = await request.form()
        message = str(form.get("message", ""))
        raw_image = form.get("image")
        if isinstance(raw_image, UploadFile):
            image = raw_image
    elif "application/json" in content_type:
        body_data: object = await request.json()
        if isinstance(body_data, dict):
            message = str(body_data.get("message", ""))
    else:
        form = await request.form()
        message = str(form.get("message", ""))

    if not message and image is None:
        raise HTTPException(status_code=400, detail="Message or image is required")

    accounts = load_accounts()
    api_key, acct = require_session(accounts, authorization)

    username = str(acct.get("username", ""))
    display_name = str(acct.get("display_name", username))

    is_allowed, reason = check_message_rate_limit(api_key)
    if not is_allowed:
        raise HTTPException(status_code=429, detail=reason)

    word_count = len(message.split()) if message else 0
    if word_count > MAX_WORDS:
        raise HTTPException(
            status_code=400,
            detail=f"Message exceeds {MAX_WORDS} words (submitted: {word_count})",
        )

    if message:
        moderation = await moderate_message(message, display_name)
        injection = await screen_injection(message, display_name)
        log_moderation(
            display_name,
            message,
            moderation,
            source="mailbox",
            injection=injection,
        )
        if not moderation.allowed:
            raise HTTPException(
                status_code=400, detail="Message could not be accepted."
            )
        if not injection.safe:
            logger.warning(
                "mailbox_injection_flagged",
                username=username,
                threat=injection.threat,
                detail=injection.detail,
            )

    attachment_meta: dict[str, str | int] | None = None

    if image is not None:
        image_data = await image.read()
        try:
            fmt, ext, mime = validate_image(image_data)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        image_data = sanitize_image(image_data, fmt)

        msg_id = generate_message_id(username, "u")
        filename = store_attachment(username, msg_id, image_data, ext)
        attachment_meta = {
            "filename": filename,
            "mime": mime,
            "size": len(image_data),
        }
    else:
        msg_id = generate_message_id(username, "u")

    now = datetime.now(UTC).isoformat()

    message_obj: MessageDict = {
        "id": msg_id,
        "from": username,
        "ts": now,
        "body": message,
    }
    if attachment_meta is not None:
        message_obj["attachment"] = attachment_meta

    append_to_thread(username, message_obj)
    record_message_usage(api_key)

    logger.info(
        "mailbox_message_sent",
        username=username,
        message_id=msg_id,
        word_count=word_count,
        has_attachment=attachment_meta is not None,
    )

    return SendResponse(
        id=msg_id,
        word_count=word_count,
        attachment=AttachmentInfo(**attachment_meta) if attachment_meta else None,  # type: ignore[arg-type]
    )


@router.get("/attachments/{username}/{filename}")
async def get_attachment(
    username: str,
    filename: str,
    authorization: str = Header(..., description="Bearer session token"),
) -> Response:
    """Serve a mailbox attachment. User can only access their own attachments."""
    accounts = load_accounts()
    _, acct = require_session(accounts, authorization)

    if acct.get("username") != username:
        raise HTTPException(status_code=403, detail="Access denied")

    filepath = get_attachment_path(username, filename)
    if filepath is None:
        raise HTTPException(status_code=404, detail="Attachment not found")

    mime = get_mime_type(filename)
    data = filepath.read_bytes()

    return Response(
        content=data,
        media_type=mime,
        headers={"Cache-Control": "private, max-age=86400"},
    )
