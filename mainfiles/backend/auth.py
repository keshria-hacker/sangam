"""Local, single-user authentication for the Sangam v1 application.

Supports both Bearer token (Authorization header) and HTTP-only cookie
based auth.  When a cookie is present both are checked — the cookie takes
priority so the frontend never needs to manage tokens in JS for browser
sessions.
"""
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from backend.database import get_db
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from loguru import logger
from backend.models import AuthSession, PasswordResetToken, User
from backend.ratelimit_redis import get_rate_limit_store
from backend.schemas import (
    AuthCredentialsIn,
    AuthStatusOut,
    AuthTokenOut,
    ForgotPasswordIn,
    ForgotPasswordOut,
    ResetPasswordIn,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings

router = APIRouter(prefix="/auth", tags=["authentication"])
SESSION_LIFETIME = timedelta(days=30)

# Brute-force lockout: after MAX_LOGIN_ATTEMPTS consecutive failed logins
# the username is blocked for LOGIN_LOCKOUT_SECONDS (sliding window). A
# successful login resets the counter, so valid users never lock out.
MAX_LOGIN_ATTEMPTS = 5
LOGIN_LOCKOUT_SECONDS = 900

# Cookie name for HTTP-only session token
AUTH_COOKIE_NAME = "sangam_session"
# CSRF cookie name (double-submit cookie pattern)
CSRF_COOKIE_NAME = "sangam_csrf"
# Header name for CSRF token
CSRF_HEADER_NAME = "X-CSRF-Token"


def _hash_password(password: str, salt: str) -> str:
    return hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt), n=2**14, r=8, p=1).hex()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _issue_token() -> str:
    return secrets.token_urlsafe(32)


def _issue_csrf_token() -> str:
    """Short token for CSRF protection (not sensitive, not stored)."""
    return secrets.token_urlsafe(16)


# Auth entry-point paths that don't require CSRF - they grant access, not protect it.
# These endpoints set the CSRF cookie; they shouldn't require one on the first call.
# Note: logout is NOT in this list - it should have CSRF protection since it's state-changing
CSRF_SKIP_PATHS = frozenset({
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/forgot-password",
    "/api/auth/reset-password",
})


async def verify_csrf(request: Request) -> None:
    """Validate CSRF token for state-changing requests. Raise 403 on failure."""
    if request.method in ("GET", "HEAD", "OPTIONS", "TRACE"):
        return
    if request.url.path in CSRF_SKIP_PATHS:
        return

    # Only enforce CSRF for cookie-based sessions (not Bearer token clients)
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    if not cookie_token:
        return  # No cookie session = no CSRF risk

    header_token = request.headers.get(CSRF_HEADER_NAME)
    if not header_token:
        raise HTTPException(
            status_code=403,
            detail="CSRF token required. Include X-CSRF-Token header."
        )

    if not hmac.compare_digest(cookie_token, header_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")


async def _clean_expired_sessions(db: AsyncSession) -> None:
    """Remove stale sessions so the sessions table stays lean."""
    result = await db.execute(
        select(AuthSession).where(AuthSession.expires_at <= datetime.now(UTC))
    )
    for session in result.scalars().all():
        await db.delete(session)
    await db.commit()


async def _create_session(user: User, db: AsyncSession, response: Response | None = None) -> AuthTokenOut:
    token = _issue_token()
    # Clean old sessions for this user (keep only the latest)
    result = await db.execute(
        select(AuthSession).where(AuthSession.user_id == user.id)
    )
    for old_session in result.scalars().all():
        await db.delete(old_session)
    await db.commit()

    db.add(AuthSession(
        user_id=user.id,
        token_hash=_hash_token(token),
        expires_at=datetime.now(UTC) + SESSION_LIFETIME,
    ))
    await db.commit()

    out = AuthTokenOut(access_token=token, username=user.username)

    # Also set an HTTP-only cookie if a Response object is available
    if response is not None:
        max_age = int(SESSION_LIFETIME.total_seconds())
        response.set_cookie(
            key=AUTH_COOKIE_NAME,
            value=token,
            max_age=max_age,
            expires=datetime.now(UTC) + SESSION_LIFETIME,
            httponly=True,
            secure=settings.ENV == "production",
            samesite="lax",
            path="/",
        )
        # CSRF token as non-httponly cookie (readable by JS)
        csrf = _issue_csrf_token()
        response.set_cookie(
            key=CSRF_COOKIE_NAME,
            value=csrf,
            max_age=max_age,
            expires=datetime.now(UTC) + SESSION_LIFETIME,
            httponly=False,          # JS needs to read it
            secure=settings.ENV == "production",
            samesite="strict",
            path="/",
        )
        out.csrf_token = csrf

    return out


async def get_current_user(
    request: Request,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    # Check HTTP-only cookie first (more secure for browser clients)
    token: str | None = None
    cookie_token = request.cookies.get(AUTH_COOKIE_NAME)
    if cookie_token:
        token = cookie_token

    # Fall back to Authorization header (for API clients / mobile)
    if token is None and authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()

    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in is required")

    token_hash = _hash_token(token)
    result = await db.execute(
        select(AuthSession, User)
        .join(User, User.id == AuthSession.user_id)
        .where(AuthSession.token_hash == token_hash, AuthSession.expires_at > datetime.now(UTC))
    )
    record = result.first()
    if record is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Your session has expired. Please sign in again.")
    return record[1]


@router.get("/status", response_model=AuthStatusOut)
async def auth_status(db: AsyncSession = Depends(get_db)):
    user_count = await db.scalar(select(func.count()).select_from(User))
    return AuthStatusOut(registration_open=not bool(user_count))


@router.post("/register", response_model=AuthTokenOut, status_code=status.HTTP_201_CREATED)
async def register(credentials: AuthCredentialsIn, response: Response, db: AsyncSession = Depends(get_db)):
    user_count = await db.scalar(select(func.count()).select_from(User))
    if user_count:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="An account already exists. Please sign in.")

    # Enforce minimum password strength
    password = credentials.password
    if len(password) < 10:
        raise HTTPException(status_code=422, detail="Password must be at least 10 characters long.")
    if not any(c.isupper() for c in password):
        raise HTTPException(status_code=422, detail="Password must contain at least one uppercase letter.")
    if not any(c.islower() for c in password):
        raise HTTPException(status_code=422, detail="Password must contain at least one lowercase letter.")
    if not any(c.isdigit() for c in password):
        raise HTTPException(status_code=422, detail="Password must contain at least one digit.")

    await _clean_expired_sessions(db)

    salt = secrets.token_hex(16)
    user = User(
        username=credentials.username.strip(),
        password_salt=salt,
        password_hash=_hash_password(credentials.password, salt),
    )
    db.add(user)
    await db.flush()
    return await _create_session(user, db, response)


@router.post("/login", response_model=AuthTokenOut)
async def login(credentials: AuthCredentialsIn, response: Response, db: AsyncSession = Depends(get_db)):
    # Brute-force lockout: a username locked out by too many failed logins
    # is rejected before any database work happens.
    store = await get_rate_limit_store()
    fail_key = f"login_fail:{credentials.username.strip()}"
    allowed, _ = await store.check_limit(fail_key, MAX_LOGIN_ATTEMPTS, LOGIN_LOCKOUT_SECONDS)
    if not allowed:
        logger.warning(
            "Login lockout for user '{username}' after {max_attempts} failed attempts; "
            "try again in {seconds}s",
            username=credentials.username,
            max_attempts=MAX_LOGIN_ATTEMPTS,
            seconds=LOGIN_LOCKOUT_SECONDS,
        )
        raise HTTPException(
            status_code=429,
            detail="Too many failed login attempts. Please try again later.",
        )

    await _clean_expired_sessions(db)
    user = await db.scalar(select(User).where(User.username == credentials.username.strip()))
    if user is None or not hmac.compare_digest(user.password_hash, _hash_password(credentials.password, user.password_salt)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    # A correct password clears the failure counter so valid users are never locked out.
    await store.reset_limit(fail_key)
    return await _create_session(user, db, response)


@router.get("/me")
async def current_user(request: Request, user: User = Depends(get_current_user)):
    """Return current user info. Also used as a session-liveness check."""
    return {"username": user.username, "authenticated": True, "session_from": "cookie" if request.cookies.get(AUTH_COOKIE_NAME) else "header"}


@router.post("/forgot-password", response_model=ForgotPasswordOut)
async def forgot_password(payload: ForgotPasswordIn, db: AsyncSession = Depends(get_db)):
    """Request a password reset token.

    In local/development mode (the default) the token is returned directly
    in the response and shown inline in the UI — there's no email system,
    and this is a single-user app running on your own machine, so that's
    a reasonable trade-off for convenience.

    Once ``ENV=production`` is set (which the README already instructs
    operators to do before exposing this app beyond localhost), the token
    is NOT returned over HTTP. It's logged server-side instead (console +
    logs/app.log), where only someone with shell/log access to the host
    can read it — otherwise this endpoint would let anyone who knows a
    username take over the account with zero authentication.

    For a real production deployment, replace the server-side log line
    below with an actual email-send call.
    """
    user = await db.scalar(select(User).where(User.username == payload.username.strip()))
    if user is None:
        # Deliberately vague — don't reveal whether the username exists
        return ForgotPasswordOut(
            message="If that username exists, a password reset token would be issued.",
            reset_token=None,
        )

    now = datetime.now(UTC)

    # Purge any previously expired tokens for this user
    result = await db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.expires_at <= now,
            PasswordResetToken.user_id == user.id,
        )
    )
    for stale in result.scalars().all():
        await db.delete(stale)
    await db.commit()

    raw_token = _issue_token()
    db.add(PasswordResetToken(
        user_id=user.id,
        token_hash=_hash_token(raw_token),
        expires_at=now + timedelta(minutes=30),
    ))
    await db.commit()

    if settings.ENV == "production":
        # Never put the token on the wire in production — only whoever can
        # read the server's own logs should be able to see it.
        logger.warning(
            "Password reset requested for user '{username}'. Reset token "
            "(valid 30 min): {token}",
            username=user.username,
            token=raw_token,
        )
        return ForgotPasswordOut(
            message=(
                "If that username exists, a password reset token has been "
                "generated. Check the server console/logs for the token "
                "(it expires in 30 minutes)."
            ),
            reset_token=None,
        )

    return ForgotPasswordOut(
        message="Use the token below to set a new password. It expires in 30 minutes.",
        reset_token=raw_token,
    )


@router.post("/reset-password")
async def reset_password(payload: ResetPasswordIn, db: AsyncSession = Depends(get_db)):
    """Reset the password using a token obtained from /forgot-password."""
    # Same password-strength checks used at registration
    pw = payload.new_password
    if len(pw) < 10:
        raise HTTPException(422, "Password must be at least 10 characters long.")
    if not any(c.isupper() for c in pw):
        raise HTTPException(422, "Password must contain at least one uppercase letter.")
    if not any(c.islower() for c in pw):
        raise HTTPException(422, "Password must contain at least one lowercase letter.")
    if not any(c.isdigit() for c in pw):
        raise HTTPException(422, "Password must contain at least one digit.")

    token_hash = _hash_token(payload.reset_token)
    now = datetime.now(UTC)

    result = await db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.used.is_(False),
            PasswordResetToken.expires_at > now,
        )
    )
    reset_token = result.scalar_one_or_none()
    if reset_token is None:
        raise HTTPException(400, "Invalid or expired reset token.")

    user = await db.get(User, reset_token.user_id)
    if user is None:
        raise HTTPException(400, "User not found.")

    # Rotate the salt and hash the new password
    user.password_salt = secrets.token_hex(16)
    user.password_hash = _hash_password(pw, user.password_salt)

    # Mark the token as single-use — no replay attacks
    reset_token.used = True

    # Invalidate ALL existing sessions so every client must re-login
    result = await db.execute(
        select(AuthSession).where(AuthSession.user_id == user.id)
    )
    for session in result.scalars().all():
        await db.delete(session)
    await db.commit()

    return {"message": "Password reset successfully. Please sign in with your new password."}


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    request: Request,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Clear the server-side session
    token: str | None = request.cookies.get(AUTH_COOKIE_NAME)
    if token is None and authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()

    if token:
        token_hash = _hash_token(token)
        session = await db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash))
        if session:
            await db.delete(session)
            await db.commit()

    # Clear cookies on the client
    response.delete_cookie(key=AUTH_COOKIE_NAME, path="/")
    response.delete_cookie(key=CSRF_COOKIE_NAME, path="/")
