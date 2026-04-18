"""User service: CRUD user use-cases."""

from __future__ import annotations

import asyncpg

from models.exceptions import ConflictError, NotFoundError
from models.request import UserCreate, UserUpdate
from repositories import user as user_repo


async def create_user(conn: asyncpg.Connection, data: UserCreate) -> dict:
    existing = await user_repo.get_by_id(conn, data.id)
    if existing:
        raise ConflictError(f"User {data.id} already exists")

    if data.email:
        existing_email = await user_repo.get_by_email(conn, data.email)
        if existing_email:
            raise ConflictError(f"Email {data.email} is already in use")

    return await user_repo.insert(
        conn,
        user_id=data.id,
        full_name=data.full_name,
        email=data.email,
        phone_number=data.phone_number,
        date_of_birth=data.date_of_birth,
        gender=data.gender,
        metadata=data.metadata,
    )


async def list_users(conn: asyncpg.Connection) -> list[dict]:
    return await user_repo.get_all(conn)


async def get_user(conn: asyncpg.Connection, user_id: str) -> dict:
    result = await user_repo.get_by_id(conn, user_id)
    if not result:
        raise NotFoundError(f"User {user_id} not found")
    return result


async def update_user(conn: asyncpg.Connection, user_id: str, data: UserUpdate) -> dict:
    if data.email:
        existing_email = await user_repo.get_by_email(conn, data.email)
        if existing_email and existing_email.get("id") != user_id:
            raise ConflictError(f"Email {data.email} is already in use")

    result = await user_repo.update(
        conn,
        user_id=user_id,
        full_name=data.full_name,
        email=data.email,
        phone_number=data.phone_number,
        date_of_birth=data.date_of_birth,
        gender=data.gender,
        metadata=data.metadata,
    )
    if not result:
        raise NotFoundError(f"User {user_id} not found")
    return result