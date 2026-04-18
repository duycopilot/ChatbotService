"""Repository helpers for users table."""

from __future__ import annotations

import json

import asyncpg


async def insert(
	conn: asyncpg.Connection,
	*,
	user_id: str,
	full_name: str | None,
	email: str | None,
	phone_number: str | None,
	date_of_birth,
	gender: str | None,
	metadata: dict | None,
) -> dict:
	sql = """
		INSERT INTO users (
			id,
			full_name,
			email,
			phone_number,
			date_of_birth,
			gender,
			metadata
		)
		VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
		RETURNING *
	"""
	row = await conn.fetchrow(
		sql,
		user_id,
		full_name,
		email,
		phone_number,
		date_of_birth,
		gender,
		json.dumps(metadata or {}),
	)
	return dict(row)


async def get_all(conn: asyncpg.Connection) -> list[dict]:
	rows = await conn.fetch("SELECT * FROM users ORDER BY created_at DESC")
	return [dict(row) for row in rows]


async def get_by_id(conn: asyncpg.Connection, user_id: str) -> dict | None:
	row = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
	return dict(row) if row else None


async def get_by_email(conn: asyncpg.Connection, email: str) -> dict | None:
	row = await conn.fetchrow("SELECT * FROM users WHERE email = $1", email)
	return dict(row) if row else None


async def update(
	conn: asyncpg.Connection,
	*,
	user_id: str,
	full_name: str | None,
	email: str | None,
	phone_number: str | None,
	date_of_birth,
	gender: str | None,
	metadata: dict | None,
) -> dict | None:
	sql = """
		UPDATE users
		SET full_name = COALESCE($2, full_name),
			email = COALESCE($3, email),
			phone_number = COALESCE($4, phone_number),
			date_of_birth = COALESCE($5, date_of_birth),
			gender = COALESCE($6, gender),
			metadata = CASE
				WHEN $7::jsonb IS NULL THEN metadata
				ELSE COALESCE(metadata, '{}'::jsonb) || $7::jsonb
			END,
			updated_at = CURRENT_TIMESTAMP
		WHERE id = $1
		RETURNING *
	"""
	row = await conn.fetchrow(
		sql,
		user_id,
		full_name,
		email,
		phone_number,
		date_of_birth,
		gender,
		json.dumps(metadata) if metadata is not None else None,
	)
	return dict(row) if row else None