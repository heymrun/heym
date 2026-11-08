from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_client_ip, get_current_user
from app.config import settings
from app.db.models import CredentialType, User
from app.db.session import get_db
from app.models.schemas import (
    LoginResponse,
    MfaChallengeResponse,
    MfaLoginRequest,
    MfaSetupResponse,
    PasswordChangeRequest,
    TokenRefresh,
    TokenResponse,
    UserCreate,
    UserLogin,
    UserResponse,
    UserUpdate,
)
from app.services import mfa
from app.services.account_status import (
    DEACTIVATED_DETAIL,
    mark_signed_in,
    meets_mfa_policy,
    revoke_sessions,
)
from app.services.audit_log import OUTCOME_DENIED, OUTCOME_FAILURE, audit
from app.services.auth import (
    SIGN_IN_MFA,
    SIGN_IN_PASSWORD,
    create_access_token,
    create_refresh_token,
    hash_password,
    read_access_claims,
    read_refresh_claims,
    revoke_refresh_token,
    rotate_refresh_token,
    store_refresh_token,
    verify_password,
    verify_refresh_token,
)
from app.services.auth_rate_limiter import login_limiter, register_limiter
from app.services.credential_access import get_accessible_credential
from app.services.sso_settings import get_sso_settings, password_login_blocked
from app.services.user_lookup import find_user_by_email

router = APIRouter()


def _is_local_http_origin(origin: str) -> bool:
    """Return True when an origin is plain HTTP for a local development host."""
    parsed = urlparse(origin.strip())
    hostname = parsed.hostname or ""
    return parsed.scheme == "http" and hostname in {"localhost", "127.0.0.1", "::1"}


def _should_use_secure_auth_cookies(frontend_url: str, cors_origins: list[str]) -> bool:
    """Use insecure cookies only for explicit local HTTP development origins."""
    frontend = frontend_url.strip()
    if frontend and not _is_local_http_origin(frontend):
        return True

    origins = [origin.strip() for origin in cors_origins if origin.strip()]
    if not origins:
        return not frontend or not _is_local_http_origin(frontend)

    return not all(_is_local_http_origin(origin) for origin in origins)


_COOKIE_SECURE = _should_use_secure_auth_cookies(settings.frontend_url, settings.cors_origins_list)
_ACCESS_COOKIE_MAX_AGE = settings.jwt_access_token_expire_minutes * 60
_REFRESH_COOKIE_MAX_AGE = settings.jwt_refresh_token_expire_days * 86400

# The refresh-token cookie must be readable by both /api/auth/refresh (to
# issue new tokens) and /api/auth/logout (to revoke the token in the DB).
# Path "/api/auth/" covers both endpoints while still excluding all other
# routes from receiving the cookie.
_REFRESH_COOKIE_PATH = "/api/auth/"


def _set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    """Set HttpOnly SameSite auth cookies on a response."""
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        samesite="lax",
        secure=_COOKIE_SECURE,
        max_age=_ACCESS_COOKIE_MAX_AGE,
        path="/",
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        samesite="lax",
        secure=_COOKIE_SECURE,
        max_age=_REFRESH_COOKIE_MAX_AGE,
        path=_REFRESH_COOKIE_PATH,
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path=_REFRESH_COOKIE_PATH)


async def register_account(
    db: AsyncSession, user_data: UserCreate, ip: str, *, client: str | None = None
) -> User:
    """Apply every registration rule and create the user, or raise."""
    allowed, retry_after = register_limiter.is_allowed(ip)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many registration attempts. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )

    if not settings.allow_register:
        audit(
            action="auth.register",
            outcome=OUTCOME_DENIED,
            actor_email=user_data.email,
            reason="registration_disabled",
            client=client,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Registration is disabled",
        )

    # Registration mints a password, so it is a password surface too. Leaving it open would
    # make "disable password sign-in" bypassable by anyone who can reach /register.
    sso_row = await get_sso_settings(db)
    if password_login_blocked(sso_row, user_data.email):
        audit(
            action="auth.register",
            outcome=OUTCOME_DENIED,
            actor_email=user_data.email,
            reason="password_login_disabled",
            client=client,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Password sign-in is disabled on this instance. Use SSO.",
        )

    # Addresses compare case-insensitively everywhere else, so a case variant is not a new account.
    if await find_user_by_email(db, user_data.email) is not None:
        audit(
            action="auth.register",
            outcome=OUTCOME_FAILURE,
            actor_email=user_data.email,
            reason="email_already_registered",
            client=client,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    user = User(
        email=user_data.email,
        hashed_password=hash_password(user_data.password),
        name=user_data.name,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


async def password_sign_in(
    db: AsyncSession, user_data: UserLogin, ip: str, *, client: str | None = None
) -> User:
    """Apply every password sign-in rule and return the user, or raise."""
    allowed, retry_after = login_limiter.is_allowed(ip)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )

    sso_row = await get_sso_settings(db)
    if password_login_blocked(sso_row, user_data.email):
        audit(
            action="auth.login",
            outcome=OUTCOME_DENIED,
            actor_email=user_data.email,
            reason="password_login_disabled",
            client=client,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Password sign-in is disabled on this instance. Use SSO.",
        )

    user = await find_user_by_email(db, user_data.email)
    if user is None or not verify_password(user_data.password, user.hashed_password):
        audit(
            action="auth.login",
            outcome=OUTCOME_FAILURE,
            actor_email=user_data.email,
            reason="unknown_email" if user is None else "bad_password",
            client=client,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    # Told only after the password is right, so the message reveals nothing to a guesser.
    if not user.is_active:
        audit(
            action="auth.login",
            outcome=OUTCOME_DENIED,
            actor=user,
            reason="account_deactivated",
            client=client,
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=DEACTIVATED_DETAIL)
    return user


def mfa_challenge_for(user: User, *, client: str | None) -> MfaChallengeResponse | None:
    """The second step a password sign-in still needs, or None when it is complete."""
    requirement = mfa.password_sign_in_requirement(user)
    if requirement is None:
        return None
    setup = None
    if requirement == mfa.PURPOSE_ENROLL:
        offer = mfa.create_setup_offer(user)
        setup = MfaSetupResponse(
            setup_token=offer.setup_token,
            secret=offer.secret,
            otpauth_uri=offer.otpauth_uri,
            qr_code=offer.qr_code,
        )
    return MfaChallengeResponse(
        purpose=requirement,
        challenge_token=mfa.create_challenge_token(user.id, requirement, client=client),
        setup=setup,
    )


_CHALLENGE_EXPIRED = "This sign-in attempt expired. Sign in again."
_CODE_INVALID = "That code is not valid. Check your authenticator app and try again."


async def mfa_sign_in(
    db: AsyncSession, body: MfaLoginRequest, *, client: str | None
) -> tuple[User, list[str] | None, str]:
    """Answer a sign-in challenge. Returns the user, any new recovery codes, and the method."""
    claims = mfa.read_challenge_token(body.challenge_token)
    if claims is None or claims.client != client:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_CHALLENGE_EXPIRED)
    allowed, retry_after = mfa.mfa_limiter.is_allowed(str(claims.user_id))
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )
    result = await db.execute(select(User).where(User.id == claims.user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_CHALLENGE_EXPIRED)

    if claims.purpose == mfa.PURPOSE_ENROLL:
        secret = mfa.read_setup_secret(body.setup_token or "", user.id)
        if secret is None or mfa.mfa_enabled(user):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_CHALLENGE_EXPIRED)
        codes = await mfa.enable_mfa(db, user, secret, body.code)
        if codes is None:
            audit(action="auth.mfa_enable", outcome=OUTCOME_FAILURE, actor=user, client=client)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_CODE_INVALID)
        audit(action="auth.mfa_enable", actor=user, client=client, during="sign_in")
        return user, codes, "totp"

    method = await mfa.verify_second_factor(db, user, body.code)
    if method is None:
        audit(action="auth.mfa_verify", outcome=OUTCOME_FAILURE, actor=user, client=client)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_CODE_INVALID)
    return user, None, method


async def _issue_session(
    db: AsyncSession, response: Response, user: User, method: str
) -> LoginResponse:
    access_token = create_access_token(user.id, method=method)
    refresh_token = create_refresh_token(user.id, method=method)
    await store_refresh_token(db, refresh_token, user.id)
    _set_auth_cookies(response, access_token, refresh_token)
    return LoginResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/register", response_model=LoginResponse, status_code=status.HTTP_201_CREATED)
async def register(
    user_data: UserCreate,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    user = await register_account(db, user_data, get_client_ip(request))
    audit(action="auth.register", actor=user)

    # With HEYM_REQUIRE_MFA a new account enrols before it holds any session.
    challenge = mfa_challenge_for(user, client=None)
    if challenge is not None:
        audit(action="auth.mfa_challenge", actor=user, purpose=challenge.purpose)
        return LoginResponse(mfa=challenge)
    mark_signed_in(user)
    return await _issue_session(db, response, user, SIGN_IN_PASSWORD)


@router.post("/login", response_model=LoginResponse)
async def login(
    user_data: UserLogin,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    user = await password_sign_in(db, user_data, get_client_ip(request))

    challenge = mfa_challenge_for(user, client=None)
    if challenge is not None:
        audit(action="auth.mfa_challenge", actor=user, purpose=challenge.purpose)
        return LoginResponse(mfa=challenge)

    mark_signed_in(user)
    session = await _issue_session(db, response, user, SIGN_IN_PASSWORD)
    audit(action="auth.login", actor=user)
    return session


@router.post("/login/mfa", response_model=LoginResponse)
async def login_mfa(
    body: MfaLoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    """Finish a password sign-in with an authenticator or recovery code."""
    user, recovery_codes, method = await mfa_sign_in(db, body, client=None)
    mark_signed_in(user)
    session = await _issue_session(db, response, user, SIGN_IN_MFA)
    session.recovery_codes = recovery_codes
    audit(action="auth.login", actor=user, mfa=method)
    return session


@router.post("/refresh", response_model=TokenResponse)
async def refresh_tokens(
    token_data: TokenRefresh,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    # Accept refresh token from either JSON body or HttpOnly cookie
    raw_refresh = token_data.refresh_token or request.cookies.get("refresh_token", "")
    if not raw_refresh:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token missing",
        )
    token_data = TokenRefresh(refresh_token=raw_refresh)  # type: ignore[assignment]
    claims = read_refresh_claims(token_data.refresh_token)
    if claims is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )
    if claims.client is not None:
        audit(
            action="auth.token_refresh",
            outcome=OUTCOME_DENIED,
            actor_id=claims.user_id,
            reason="client_bound_token",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This token can only be refreshed by the client it was issued to",
        )
    user_id = claims.user_id

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    if not meets_mfa_policy(
        claims.method,
        has_password=bool(user.hashed_password),
        has_sso_identity=bool(user.sso_subject),
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in again to set up two-factor authentication.",
        )

    new_access_token = create_access_token(user.id, method=claims.method)
    new_refresh_token = create_refresh_token(user.id, method=claims.method)

    rotated = await rotate_refresh_token(db, token_data.refresh_token, new_refresh_token, user.id)
    if not rotated:
        audit(
            action="auth.token_refresh",
            outcome=OUTCOME_DENIED,
            actor=user,
            reason="refresh_token_replayed_or_revoked",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token already used or revoked",
        )

    _set_auth_cookies(response, new_access_token, new_refresh_token)
    audit(action="auth.token_refresh", actor=user)
    return TokenResponse(access_token=new_access_token, refresh_token=new_refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Clear auth cookies and revoke the refresh token in the database."""
    raw_refresh = request.cookies.get("refresh_token", "")
    actor_id = verify_refresh_token(raw_refresh) if raw_refresh else None
    if raw_refresh:
        await revoke_refresh_token(db, raw_refresh)
    _clear_auth_cookies(response)
    audit(action="auth.logout", actor_id=actor_id)


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse.model_validate(current_user)


@router.put("/me", response_model=UserResponse)
async def update_me(
    user_data: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    if user_data.name is not None:
        current_user.name = user_data.name
    if user_data.user_rules is not None:
        current_user.user_rules = user_data.user_rules
    if user_data.tts_credential_id is not None:
        credential = await get_accessible_credential(
            db, user_data.tts_credential_id, current_user.id
        )
        if credential is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Credential not found",
            )
        if credential.type != CredentialType.elevenlabs:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="TTS credential must be an ElevenLabs credential",
            )
        current_user.tts_credential_id = user_data.tts_credential_id
    if user_data.tts_voice_id is not None:
        current_user.tts_voice_id = user_data.tts_voice_id or None
    if user_data.preferred_credential_id is not None:
        preferred = await get_accessible_credential(
            db, user_data.preferred_credential_id, current_user.id
        )
        if preferred is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Preferred credential not found",
            )
        current_user.preferred_credential_id = user_data.preferred_credential_id
    if user_data.preferred_model is not None:
        current_user.preferred_model = user_data.preferred_model or None

    await db.flush()
    await db.refresh(current_user)

    return UserResponse.model_validate(current_user)


def _current_method(request: Request) -> str:
    """How the caller's own session began, kept when its tokens are reissued."""
    header = request.headers.get("Authorization", "")
    token = header[7:] if header.startswith("Bearer ") else request.cookies.get("access_token")
    claims = read_access_claims(token or "")
    if claims is None or claims.method is None:
        return SIGN_IN_PASSWORD
    return claims.method


@router.post("/sessions/revoke-others", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_other_sessions(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Sign out every other browser, device, Heym Work session, and MCP OAuth client."""
    await revoke_sessions(db, current_user)
    await _issue_session(db, response, current_user, _current_method(request))
    audit(action="auth.sessions_revoke", actor=current_user, scope="others")


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    password_data: PasswordChangeRequest,
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    if not verify_password(password_data.current_password, current_user.hashed_password):
        audit(
            action="auth.password_change",
            outcome=OUTCOME_FAILURE,
            actor=current_user,
            reason="current_password_incorrect",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect",
        )

    current_user.hashed_password = hash_password(password_data.new_password)
    # Whoever knew the old password keeps no session; this browser gets a fresh one.
    await revoke_sessions(db, current_user)
    await _issue_session(db, response, current_user, _current_method(request))
    audit(action="auth.password_change", actor=current_user)
