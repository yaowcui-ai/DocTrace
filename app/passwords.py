from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError


_password_hasher = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        return _password_hasher.verify(password, stored_hash)
    except UnknownHashError:
        return False