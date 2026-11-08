import base64
import hashlib
import json

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.config import settings
from app.services.k8s_credentials.store import is_pointer
from app.services.k8s_credentials.store import store as k8s_credential_store


def fernet_for(key: str) -> Fernet:
    """The Fernet a configured key stands for. Unchanged, so existing data decrypts."""
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest()))


def get_fernet() -> Fernet:
    """The primary key's Fernet: everything is encrypted with ENCRYPTION_KEY."""
    return fernet_for(settings.encryption_key)


def get_multi_fernet() -> MultiFernet:
    """ENCRYPTION_KEY, then ENCRYPTION_KEYS_EXTRA: decrypts with any, encrypts with the first."""
    return MultiFernet([fernet_for(key) for key in settings.encryption_keys])


def encrypt_config(config: dict) -> str:
    fernet = get_fernet()
    json_str = json.dumps(config)
    encrypted = fernet.encrypt(json_str.encode())
    return encrypted.decode()


def encrypt_text(value: str) -> str:
    """Encrypt one string under ENCRYPTION_KEY."""
    return get_fernet().encrypt(value.encode()).decode()


def decrypt_text(token: str) -> str:
    """Decrypt a string written by `encrypt_text`, with any configured key."""
    return get_multi_fernet().decrypt(token.encode()).decode()


def readable_by_primary(token: str) -> bool:
    """Whether ENCRYPTION_KEY alone decrypts this token, i.e. it needs no re-encryption."""
    try:
        get_fernet().decrypt(token.encode())
    except InvalidToken:
        return False
    return True


def rotate_token(token: str) -> str:
    """Re-encrypt a token under ENCRYPTION_KEY, keeping its timestamp.

    Raises `InvalidToken` when no configured key decrypts it.
    """
    return get_multi_fernet().rotate(token.encode()).decode()


def decrypt_config(encrypted_config: str) -> dict:
    """The config a credential row holds, or, for a Secret-backed row, the Secret's.

    Every read of a credential goes through here, so resolving the `k8s:` pointer in
    this one place leaves the call sites unchanged. A Secret-backed credential with no
    value in this process raises `CredentialUnavailableError` with the reason.
    """
    if is_pointer(encrypted_config):
        return k8s_credential_store.config_for(encrypted_config)
    decrypted = get_multi_fernet().decrypt(encrypted_config.encode())
    return json.loads(decrypted.decode())


def mask_api_key(value: str, visible_chars: int = 7) -> str:
    if len(value) <= visible_chars:
        return "*" * len(value)
    return value[:visible_chars] + "**"
