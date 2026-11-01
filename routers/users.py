from typing import Annotated

from botocore.exceptions import ClientError
from fastapi import APIRouter, HTTPException, Query, UploadFile, status
from PIL import UnidentifiedImageError
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload
from starlette.concurrency import run_in_threadpool

import models
from config import settings
from database import Database
from schemas.posts import PaginatedPostsResponse, PostResponse
from schemas.users import (
    UserCreate,
    UserPrivateResponse,
    UserPublicResponse,
    UserUpdate,
)
from utils.auth import CurrentUser, hash_password
from utils.images import (
    delete_profile_image,
    process_profile_image,
    upload_profile_image,
)

router = APIRouter()


@router.get("/me", response_model=UserPrivateResponse)
async def get_current_user(
    current_user: CurrentUser,
):
    return current_user


@router.get("/{user_id}", response_model=UserPublicResponse)
async def get_user(user_id: int, db: Database):
    result = await db.execute(
        select(models.User)
        .options(selectinload(models.User.posts))
        .where(models.User.id == user_id)
    )
    user = result.scalars().first()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    return user


@router.get("/{user_id}/posts", response_model=PaginatedPostsResponse)
async def get_user_posts(
    user_id: int,
    db: Database,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
):
    result = await db.execute(
        select(models.User).where(models.User.id == user_id)
    )
    user = result.scalars().first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    count_result = await db.execute(
        select(func.count())
        .select_from(models.Post)
        .where(models.Post.user_id == user_id),
    )
    total = count_result.scalar() or 0

    result = await db.execute(
        select(models.Post)
        .options(selectinload(models.Post.author))
        .where(models.Post.user_id == user_id)
        .order_by(models.Post.date_posted.desc())
        .offset(skip)
        .limit(limit),
    )
    posts = result.scalars().all()

    has_more = skip + len(posts) < total

    return PaginatedPostsResponse(
        posts=[PostResponse.model_validate(post) for post in posts],
        total=total,
        skip=skip,
        limit=limit,
        has_more=has_more,
    )


@router.post(
    "",
    response_model=UserPrivateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_user(user: UserCreate, db: Database):
    result = await db.execute(
        select(models.User).where(
            or_(
                models.User.username == user.username,
                models.User.email == user.email,
            )
        )
    )
    existing_user = result.scalars().first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username or Email already exists",
        )

    new_user = models.User(
        username=user.username,
        email=user.email,
        password_hash=hash_password(user.password),
    )
    # Preparare l'inserimento
    db.add(new_user)
    # Esegue e salva l'inserimento
    await db.commit()
    # Ricarica l'oggetto dal db
    await db.refresh(new_user)

    return new_user


@router.patch("/{user_id}", response_model=UserPublicResponse)
async def update_user_partial(
    user_id: int,
    user_data: UserUpdate,
    current_user: CurrentUser,
    db: Database,
):
    if user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    is_updating_username = (
        user_data.username is not None
        and user_data.username != current_user.username
    )
    if is_updating_username:
        result = await db.execute(
            select(models.User).where(
                func.lower(models.User.username) == user_data.username
            ),
        )
        existing_user = result.scalars().first()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already exists",
            )

    is_updating_email = (
        user_data.email is not None and user_data.email != current_user.email
    )
    if is_updating_email:
        result = await db.execute(
            select(models.User).where(models.User.email == user_data.email),
        )
        existing_email = result.scalars().first()
        if existing_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered",
            )

    updated_data = user_data.model_dump(exclude_unset=True)
    for field, value in updated_data.items():
        setattr(current_user, field, value)

    await db.commit()
    await db.refresh(current_user)

    return current_user


@router.patch("/{user_id}/picture", response_model=UserPrivateResponse)
async def upload_profile_picture(
    user_id: int,
    file: UploadFile,
    current_user: CurrentUser,
    db: Database,
):
    if current_user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
        )

    content = await file.read()

    if len(content) > settings.max_upload_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large. Maximum size is {settings.max_upload_size_bytes // (1024 * 1024)}MB",
        )

    try:
        processed_bytes, new_filename = await run_in_threadpool(
            process_profile_image, content
        )
    except UnidentifiedImageError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid image file. Please upload a valid image (JPEG, PNG, GIF, WebP).",
        ) from err

    try:
        await upload_profile_image(processed_bytes, new_filename)
    except ClientError as err:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upload image. Please try again.",
        ) from err

    old_filename = current_user.image_file

    current_user.image_file = new_filename

    await db.commit()
    await db.refresh(current_user)

    if old_filename:
        await delete_profile_image(old_filename)

    return current_user


@router.delete("/{user_id}/picture", response_model=UserPrivateResponse)
async def delete_user_picture(
    user_id: int,
    current_user: CurrentUser,
    db: Database,
):
    if current_user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this user's picture",
        )

    old_filename = current_user.image_file

    if old_filename is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No profile picture to delete",
        )

    current_user.image_file = None
    await db.commit()
    await db.refresh(current_user)

    await delete_profile_image(old_filename)

    return current_user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: int, current_user: CurrentUser, db: Database):
    if user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    await db.delete(current_user)
    await db.commit()

    if current_user.image_file:
        await delete_profile_image(current_user.image_file)
