from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from config import settings

engine = create_async_engine(settings.database_url)

AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as db:
        yield db


type Database = Annotated[AsyncSession, Depends(get_db)]

# Collegamento ASINCRONO sqlite

# SQLALCHEMY_DATABASE_URL = "sqlite+aiosqlite:///./blog.db"

# engine = create_async_engine(
#     SQLALCHEMY_DATABASE_URL,
#     connect_args={"check_same_thread": False},
# )

# AsyncSessionLocal = async_sessionmaker(
#     bind=engine, class_=AsyncSession, expire_on_commit=False
# )


# class Base(DeclarativeBase):
#     pass


# async def get_db():
#     async with AsyncSessionLocal() as db:
#         yield db


# Collegamento SINCRONO a sqlite

# from sqlalchemy import create_engine
# from sqlalchemy.orm import DeclarativeBase, sessionmaker

# SQLALCHEMY_DATABASE_URL = "sqlite:///./blog.db"

# engine = create_engine(
#     SQLALCHEMY_DATABASE_URL,
#     connect_args={"check_same_thread": False},
# )

# SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# class Base(DeclarativeBase):
#     pass


# def get_db():
#     with SessionLocal() as db:
#         yield db
