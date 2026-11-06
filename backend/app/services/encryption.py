import base64
import hashlib
import json

from cryptography.fernet import Fernet

from app.config import settings
from app.services.k8s_credentials.store import is_pointer
from app.services.k8s_credentials.store import store as k8s_credential_store


def get_fernet() -> Fernet:
    key = hashlib.sha256(settings.encryption_key.encode()).digest()
    key_b64 = base64.urlsafe_b64encode(key)
    return Fernet(key_b64)


def encrypt_config(config: dict) -> str:
    fernet = get_fernet()
    json_str = json.dumps(config)
    encrypted = fernet.encrypt(json_str.encode())
    return encrypted.decode()


def decrypt_config(encrypted_config: str) -> dict:
    """The config a credential row holds, or, for a Secret-backed row, the Secret's.

    Every read of a credential goes through here, so resolving the `k8s:` pointer in
    this one place leaves the call sites unchanged. A Secret-backed credential with no
    value in this process raises `CredentialUnavailableError` with the reason.
    """
    if is_pointer(encrypted_config):
        return k8s_credential_store.config_for(encrypted_config)
    fernet = get_fernet()
    decrypted = fernet.decrypt(encrypted_config.encode())
    return json.loads(decrypted.decode())


def mask_api_key(value: str, visible_chars: int = 7) -> str:
    if len(value) <= visible_chars:
        return "*" * len(value)
    return value[:visible_chars] + "**"
