from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import SecretStr
from sqlalchemy import delete, select

import models
from config import settings
from database import Database
from schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    Token,
)
from utils.auth import (
    CurrentUser,
    create_access_token,
    generate_reset_token,
    hash_password,
    hash_reset_token,
    verify_password,
)
from utils.email import send_password_reset_email

router = APIRouter()


@router.post("/token", response_model=Token)
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Database,
):
    # Look up user by email (case-insensitive)
    # Note: OAuth2PasswordRequestForm uses "username" field, but we treat it as email
    result = await db.execute(
        select(models.User).where(
            models.User.email == form_data.username.lower()
        ),
    )
    user = result.scalars().first()

    # Verify user exists and password is correct
    # Don't reveal which one failed (security best practice)
    if not user or not verify_password(
        SecretStr(form_data.password), user.password_hash
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Create access token with user id as subject
    # access_token_expires = timedelta(
    #     minutes=settings.access_token_expire_minutes
    # )
    access_token = create_access_token(
        data={"sub": str(user.id)},
        # expires_delta=access_token_expires,
    )
    return Token(access_token=access_token, token_type="bearer")


@router.patch("/change-password", status_code=status.HTTP_200_OK)
async def change_password(
    password_data: ChangePasswordRequest,
    current_user: CurrentUser,
    db: Database,
):
    if not verify_password(
        password_data.current_password, current_user.password_hash
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    current_user.password_hash = hash_password(password_data.new_password)

    await db.execute(
        delete(models.PasswordResetToken).where(
            models.PasswordResetToken.user_id == current_user.id,
        ),
    )

    await db.commit()
    return {"message": "Password changed successfully"}


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
async def forgot_password(
    request_data: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: Database,
):
    result = await db.execute(
        select(models.User).where(models.User.email == request_data.email),
    )
    user = result.scalars().first()

    if user:
        await db.execute(
            delete(models.PasswordResetToken).where(
                models.PasswordResetToken.user_id == user.id,
            ),
        )

        token = generate_reset_token()
        token_hash = hash_reset_token(token)
        expires_at = datetime.now(UTC) + timedelta(
            minutes=settings.reset_pwd_token_expire_minutes
        )

        reset_token = models.PasswordResetToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        db.add(reset_token)
        await db.commit()

        # L'equivalente di after di nextjs
        # (task che viene eseguita dopo la consegna della risposta)
        background_tasks.add_task(
            send_password_reset_email,
            to_email=user.email,
            username=user.username,
            token=token,
        )

    return {
        "message": "If an account exists with this email, you will receive password reset instructions."
    }


@router.post("/reset-password", status_code=status.HTTP_200_OK)
async def reset_password(
    request_data: ResetPasswordRequest,
    db: Database,
):
    token_hash = hash_reset_token(request_data.token)

    result = await db.execute(
        select(models.PasswordResetToken).where(
            models.PasswordResetToken.token_hash == token_hash,
        ),
    )
    reset_token = result.scalars().first()

    if not reset_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )

    # se usassimo sqlite al posto di postgresql dovremmo
    # settare manualmente tramite replace la timezone
    # poiche quel database non la salva
    #  if reset_token.expires_at.replace(tzinfo=UTC) < datetime.now(UTC):

    if reset_token.expires_at < datetime.now(UTC):
        await db.delete(reset_token)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )

    result = await db.execute(
        select(models.User).where(models.User.id == reset_token.user_id),
    )
    user = result.scalars().first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )

    user.password_hash = hash_password(request_data.new_password)

    await db.execute(
        delete(models.PasswordResetToken).where(
            models.PasswordResetToken.user_id == user.id,
        ),
    )

    await db.commit()
    return {
        "message": "Password reset successfully. You can now log in with your new password."
    }
