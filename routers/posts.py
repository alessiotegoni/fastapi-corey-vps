from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import selectinload

import models
from config import settings
from database import Database
from schemas.posts import (
    PaginatedPostsResponse,
    PostCreate,
    PostResponse,
    PostUpdate,
)
from utils.auth import CurrentUser

router = APIRouter()


@router.get("", response_model=PaginatedPostsResponse)
async def get_posts(
    db: Database,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = settings.posts_per_page,
):
    count_result = await db.execute(
        select(func.count()).select_from(models.Post)
    )
    total = count_result.scalar() or 0

    result = await db.execute(
        select(models.Post)
        .options(selectinload(models.Post.author))
        .order_by(models.Post.date_posted.desc())
        .offset(skip)
        .limit(limit)
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


@router.get("/{post_id}", response_model=PostResponse)
async def get_post(post_id: int, db: Database):
    result = await db.execute(
        select(models.Post)
        .options(selectinload(models.Post.author))
        .where(models.Post.id == post_id)
    )
    post = result.scalars().first()

    if post is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Post not found"
        )

    return post


@router.post(
    "",
    response_model=PostResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_post(
    post: PostCreate,
    current_user: CurrentUser,
    db: Database,
):
    new_post = models.Post(
        title=post.title, content=post.content, user_id=current_user.id
    )

    # Preparare l'inserimento
    db.add(new_post)
    # Esegue e salva l'inserimento
    await db.commit()
    # Ricarica l'oggetto dal db e lo popola quindi dei campi nuovi
    # che il db aggiunge in automatico (es. id, date, o triggers))
    # Tramite attributes_names il refresh carica le relazioni
    await db.refresh(new_post, attribute_names=["author"])

    return new_post


@router.put(
    "/{post_id}",
    response_model=PostResponse,
)
async def update_post_full(
    post_id: int,
    post_data: PostCreate,
    current_user: CurrentUser,
    db: Database,
):
    result = await db.execute(
        select(models.Post).where(models.Post.id == post_id)
    )
    post = result.scalars().first()

    if post is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Post not found"
        )

    if post.author.id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this post",
        )

    result = await db.execute(
        update(models.Post)
        .values(**post_data.model_dump())
        .where(models.Post.id == post_id)
        .returning(models.Post)
        .options(selectinload(models.Post.author))
    )

    updated_post = result.scalars().first()

    await db.commit()

    return updated_post


@router.patch("/{post_id}", response_model=PostResponse)
async def update_post_partial(
    post_id: int,
    current_user: CurrentUser,
    post_data: PostUpdate,
    db: Database,
):
    result = await db.execute(
        select(models.Post)
        .options(selectinload(models.Post.author))
        .where(models.Post.id == post_id)
    )
    post = result.scalars().first()

    if post is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Post not found"
        )

    if post.author.id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this post",
        )

    # exclude_unset = True
    # Esclude i valori non inviati dal client
    # quindi i campi a cui pydantic assegna i valori default
    # (in questo caso None)
    updated_data = post_data.model_dump(exclude_unset=True)
    for field, value in updated_data.items():
        setattr(post, field, value)

    await db.commit()
    await db.refresh(post)

    return post


@router.delete("/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_post(
    post_id: int,
    current_user: CurrentUser,
    db: Database,
):
    # (operazione) & (operazione)
    # e' l'equivalente di and_ da sqlalchemy
    result = await db.execute(
        select(models.Post).where(models.Post.id == post_id)
    )
    post = result.scalars().first()

    if post is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Post not found"
        )

    if post.author.id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this post",
        )

    await db.delete(post)
    await db.commit()
