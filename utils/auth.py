import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pwdlib import PasswordHash
from pydantic import SecretStr
from sqlalchemy import select

import models
from config import settings
from database import Database

password_hash = PasswordHash.recommended()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/token")


# Quando usare SecretStr
#
# SecretStr non cripta e non hasha: nasconde il valore quando viene stampato,
# loggato o serializzato (print, repr, model_dump_json mostrano "**********").
# Serve a evitare che un segreto finisca per sbaglio in un log o in un errore.
#
# Si usa per i segreti IN CHIARO che passano dentro il codice:
#   - password e token che arrivano nel body (schemas/)
#   - segreti di configurazione come secret_key e mail_password (config.py)
#   - il reset token generato, prima di mandarlo via mail
#
# Non si usa per:
#   - gli hash: non sono segreti in chiaro, e nel DB sono gia str
#   - i valori da restituire al client: verrebbero serializzati come
#     "**********" (per questo Token.access_token e' str)
#
# Il valore vero si legge SOLO con get_secret_value(), nel punto in cui lo
# passi alla libreria che ne ha bisogno. str(segreto) e le f-string
# restituiscono "**********" senza dare errori: e' l'errore piu facile da fare.


def hash_password(password: SecretStr) -> str:
    return password_hash.hash(password.get_secret_value())


def verify_password(plain_password: SecretStr, hashed_password: str) -> bool:
    return password_hash.verify(
        plain_password.get_secret_value(), hashed_password
    )


def create_access_token(
    data: dict[str, Any], expires_delta: timedelta | None = None
) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()

    expire = (
        datetime.now(UTC) + expires_delta
        if expires_delta
        else datetime.now(UTC)
        + timedelta(
            minutes=settings.access_token_expire_minutes,
        )
    )

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        payload=to_encode,
        key=settings.secret_key.get_secret_value(),
        algorithm=settings.algorithm,
    )
    return str(encoded_jwt)


def verify_access_token(token: str) -> str | None:
    """Verify a JWT access token and return the subject (user id) if valid."""
    try:
        payload = jwt.decode(
            token,
            key=settings.secret_key.get_secret_value(),
            algorithms=[settings.algorithm],
            options={"require": ["exp", "sub"]},
        )
    except jwt.InvalidTokenError:
        return None
    else:
        return payload.get("sub")


def generate_reset_token() -> SecretStr:
    return SecretStr(secrets.token_urlsafe(32))


def hash_reset_token(token: SecretStr) -> str:
    return hashlib.sha256(token.get_secret_value().encode()).hexdigest()


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Database,
) -> models.User:
    user_id = verify_access_token(token)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id_int = int(user_id)
    except TypeError, ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    result = await db.execute(
        select(models.User).where(models.User.id == user_id_int),
    )
    user = result.scalars().first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


type CurrentUser = Annotated[models.User, Depends(get_current_user)]
