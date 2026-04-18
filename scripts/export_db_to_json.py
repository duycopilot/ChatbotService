#!/usr/bin/env python3
"""
Continuous PostgreSQL → JSON exporter with incremental updates.

Features:
    - Runs continuously, exports every N minutes (default: 30)
    - Incremental: only appends new records, replaces updated records (by PK)
    - Persistent hash store: dedup works correctly across day boundaries
    - Auto-detect schema: groups data by user_id from foreign keys
    - Organized output:
        {base_dir}/{YYYY}/{MM}/{DD}/{user_name}/{conv_id}.json  ← messages per conversation
        {base_dir}/{YYYY}/{MM}/{DD}/{user_name}/{table}.json    ← other user-scoped tables
        {base_dir}/{YYYY}/{MM}/{DD}/{table}.json                ← global tables
    - SQL-injection safe with identifier quoting
    - Streaming cursor for large tables
    - Proper logging instead of print()

Usage:
    python export_db_to_json.py [options]
    python export_db_to_json.py --tables conversations,messages --interval 15
    python export_db_to_json.py --run-once

Environment Variables:
    DATABASE_URL       - PostgreSQL connection string
    EXPORT_OUTPUT_DIR  - Base output directory
    EXPORT_INTERVAL    - Minutes between cycles
"""

import asyncpg
import json
import argparse
import asyncio
import logging
import os
import signal
import hashlib
from pathlib import Path
from datetime import datetime, date
from uuid import UUID
from collections import defaultdict
from dataclasses import dataclass
import re

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("db_exporter")

# ---------------------------------------------------------------------------
# JSON Encoder
# ---------------------------------------------------------------------------

class JSONEncoder(json.JSONEncoder):
    """Handle UUID, datetime, date, bytes, Decimal serialization."""

    def default(self, obj):
        if isinstance(obj, UUID):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, date):
            return obj.isoformat()
        if isinstance(obj, bytes):
            return obj.hex()
        try:
            return float(obj)
        except (TypeError, ValueError):
            pass
        return super().default(obj)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _record_hash(record: dict) -> str:
    """SHA-256 hash of a record for dedup (deterministic, keys sorted)."""
    raw = json.dumps(record, sort_keys=True, cls=JSONEncoder)
    return hashlib.sha256(raw.encode()).hexdigest()


def _quote_ident(name: str) -> str:
    """Quote a SQL identifier to prevent injection."""
    return '"' + name.replace('"', '""') + '"'


# ---------------------------------------------------------------------------
# Schema introspection — detect user_id column automatically
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# User name mapping — user_id → folder name
# ---------------------------------------------------------------------------

_NAME_CANDIDATES = ["full_name", "fullname", "display_name", "name", "username", "email"]


def _sanitize_folder_name(name: str) -> str:
    """
    Turn a user name into a safe, readable folder name.
    'Nguyễn Văn A' → 'nguyen_van_a'
    """
    name = name.strip()
    name = re.sub(r"[^\w\s-]", "_", name)
    name = re.sub(r"[\s]+", "_", name)
    name = re.sub(r"_+", "_", name)
    name = name.strip("_")
    return name.lower() if name else "_unknown"


async def build_user_name_map(conn: asyncpg.Connection) -> dict[str, str]:
    """
    Build mapping {user_id: folder_name} from the users table.
    Auto-detects the name column (full_name, name, username, email, ...).
    Handles duplicate names by appending _2, _3, etc.
    """
    exists = await conn.fetchval(
        "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name = 'users')"
    )
    if not exists:
        return {}

    col_rows = await conn.fetch(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'users'"
    )
    available = {r["column_name"] for r in col_rows}

    # Detect PK
    pk_col = None
    for candidate in ["id", "user_id"]:
        if candidate in available:
            pk_col = candidate
            break
    if not pk_col:
        logger.warning("Cannot find primary key in users table")
        return {}

    # Detect name column
    name_col = None
    for candidate in _NAME_CANDIDATES:
        if candidate in available:
            name_col = candidate
            break
    if not name_col:
        logger.warning(
            "No name column found in users (checked: %s, available: %s). "
            "Falling back to user_id.",
            _NAME_CANDIDATES, sorted(available),
        )
        return {}

    logger.info("  [users] Folder names from column '%s'", name_col)

    rows = await conn.fetch(
        f"SELECT {_quote_ident(pk_col)}, {_quote_ident(name_col)} FROM users"
    )

    name_map: dict[str, str] = {}
    seen_names: dict[str, int] = {}

    for row in rows:
        uid = str(row[pk_col])
        raw_name = str(row[name_col] or "")
        folder = _sanitize_folder_name(raw_name)

        if not folder or folder == "_unknown":
            folder = uid

        # Deduplicate: "nguyen_van_a" → "nguyen_van_a", "nguyen_van_a_2"
        if folder in seen_names:
            seen_names[folder] += 1
            folder = f"{folder}_{seen_names[folder]}"
        else:
            seen_names[folder] = 1

        name_map[uid] = folder

    logger.info("  [users] Mapped %d users to folder names", len(name_map))
    return name_map


async def detect_user_column(conn: asyncpg.Connection, table: str) -> str | None:
    """
    Detect the column in *table* that references the 'users' table.
    Returns the column name (e.g. 'user_id') or None if not found.

    Strategy:
    1. Check foreign keys pointing to 'users' table
    2. Fallback: check if a 'user_id' column exists by name convention
    """
    # 1. FK-based detection
    fk_row = await conn.fetchrow(
        """
        SELECT kcu.column_name
        FROM   information_schema.table_constraints tc
        JOIN   information_schema.key_column_usage kcu
               ON tc.constraint_name = kcu.constraint_name
               AND tc.table_schema = kcu.table_schema
        JOIN   information_schema.constraint_column_usage ccu
               ON ccu.constraint_name = tc.constraint_name
               AND ccu.table_schema = tc.table_schema
        WHERE  tc.constraint_type = 'FOREIGN KEY'
        AND    tc.table_name = $1
        AND    ccu.table_name = 'users'
        LIMIT  1
        """,
        table,
    )
    if fk_row:
        return fk_row["column_name"]

    # 2. Convention-based fallback
    col_row = await conn.fetchrow(
        """
        SELECT column_name
        FROM   information_schema.columns
        WHERE  table_name = $1
        AND    column_name = 'user_id'
        LIMIT  1
        """,
        table,
    )
    if col_row:
        return col_row["column_name"]

    return None


async def detect_conversation_column(conn: asyncpg.Connection, table: str) -> str | None:
    """
    Detect column referencing conversations table (e.g. 'conversation_id').
    Used to split messages into per-conversation files.
    """
    fk_row = await conn.fetchrow(
        """
        SELECT kcu.column_name
        FROM   information_schema.table_constraints tc
        JOIN   information_schema.key_column_usage kcu
               ON tc.constraint_name = kcu.constraint_name
               AND tc.table_schema = kcu.table_schema
        JOIN   information_schema.constraint_column_usage ccu
               ON ccu.constraint_name = tc.constraint_name
               AND ccu.table_schema = tc.table_schema
        WHERE  tc.constraint_type = 'FOREIGN KEY'
        AND    tc.table_name = $1
        AND    ccu.table_name = 'conversations'
        LIMIT  1
        """,
        table,
    )
    if fk_row:
        return fk_row["column_name"]

    # Convention fallback
    col_row = await conn.fetchrow(
        """
        SELECT column_name
        FROM   information_schema.columns
        WHERE  table_name = $1
        AND    column_name = 'conversation_id'
        LIMIT  1
        """,
        table,
    )
    return col_row["column_name"] if col_row else None


async def _get_table_primary_keys(conn: asyncpg.Connection, table: str) -> list[str]:
    """Detect primary key columns for a table."""
    rows = await conn.fetch(
        """
        SELECT a.attname
        FROM   pg_index i
        JOIN   pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
        WHERE  i.indrelid = $1::regclass
        AND    i.indisprimary
        ORDER  BY array_position(i.indkey, a.attnum)
        """,
        table,
    )
    return [r["attname"] for r in rows]


@dataclass
class TableSchema:
    """Schema info for a single table."""
    user_column: str | None = None
    conversation_column: str | None = None
    primary_keys: list[str] | None = None  # for upsert logic


async def detect_schema_mapping(
    conn: asyncpg.Connection, tables: list[str]
) -> dict[str, TableSchema]:
    """
    For each table, detect user_column and conversation_column.
    """
    mapping = {}
    for table in tables:
        user_col = await detect_user_column(conn, table)
        conv_col = await detect_conversation_column(conn, table)
        try:
            pks = await _get_table_primary_keys(conn, table)
        except Exception:
            pks = []

        schema = TableSchema(
            user_column=user_col,
            conversation_column=conv_col,
            primary_keys=pks or None,
        )
        mapping[table] = schema

        parts = []
        if user_col:
            parts.append(f"user='{user_col}'")
        if conv_col:
            parts.append(f"conv='{conv_col}'")
        if pks:
            parts.append(f"pk={pks}")
        if parts:
            logger.info("  [schema] %s → %s", table, ", ".join(parts))
        else:
            logger.info("  [schema] %s → global", table)
    return mapping


# ---------------------------------------------------------------------------
# Path builders
# ---------------------------------------------------------------------------

def _build_user_output_path(
    base_dir: Path, table_name: str, user_id: str, now: datetime
) -> Path:
    """
    {base_dir}/{YYYY}/{MM}/{DD}/{user_id}/{table}.json
    """
    day_dir = (
        base_dir
        / now.strftime("%Y")
        / now.strftime("%m")
        / now.strftime("%d")
        / str(user_id)
    )
    day_dir.mkdir(parents=True, exist_ok=True)
    return day_dir / f"{table_name}.json"


def _build_global_output_path(
    base_dir: Path, table_name: str, now: datetime
) -> Path:
    """
    {base_dir}/{YYYY}/{MM}/{DD}/{table}.json
    """
    day_dir = base_dir / now.strftime("%Y") / now.strftime("%m") / now.strftime("%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    return day_dir / f"{table_name}.json"


# ---------------------------------------------------------------------------
# Persistent hash store
# ---------------------------------------------------------------------------

def _hashset_path(base_dir: Path, table_name: str) -> Path:
    """Path: {base_dir}/.state/{table}.hashes — persists across days."""
    state_dir = base_dir / ".state"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / f"{table_name}.hashes"


def _load_hashset(path: Path) -> set[str]:
    """Load persistent record hashes (one per line)."""
    if not path.exists() or path.stat().st_size == 0:
        return set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            return {line.strip() for line in f if line.strip()}
    except OSError as exc:
        logger.warning("Could not read hashset %s (%s) — starting fresh", path, exc)
        return set()


def _append_hashset(path: Path, new_hashes: list[str]) -> None:
    """Append new hashes (fast, no full rewrite)."""
    with open(path, "a", encoding="utf-8") as f:
        f.writelines(h + "\n" for h in new_hashes)


# ---------------------------------------------------------------------------
# JSON file I/O
# ---------------------------------------------------------------------------

def _load_existing_records(path: Path) -> list[dict]:
    """Load today's JSON file (or empty list if not yet created)."""
    if not path.exists() or path.stat().st_size == 0:
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read %s (%s) — starting fresh", path, exc)
        return []


def _write_json(path: Path, records: list[dict]) -> None:
    """Write records to JSON file (UTF-8, pretty-printed)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, cls=JSONEncoder, ensure_ascii=False)


def _pk_value(record: dict, pk_cols: list[str]) -> tuple:
    """Extract a composite PK tuple from a record."""
    return tuple(str(record.get(c, "")) for c in pk_cols)


def _merge_with_upsert(
    existing: list[dict],
    new_records: list[dict],
    pk_cols: list[str] | None,
) -> list[dict]:
    """
    Merge new_records into existing.
    - If pk_cols is available: records with the same PK are REPLACED (upsert).
    - If pk_cols is None: simple append (no dedup by PK).
    """
    if not pk_cols:
        return existing + new_records

    # Build index: PK → position in result list
    merged: list[dict] = list(existing)
    pk_index: dict[tuple, int] = {}
    for i, rec in enumerate(merged):
        pk_index[_pk_value(rec, pk_cols)] = i

    for rec in new_records:
        pk = _pk_value(rec, pk_cols)
        if pk in pk_index:
            # Replace existing record with updated version
            merged[pk_index[pk]] = rec
        else:
            pk_index[pk] = len(merged)
            merged.append(rec)

    return merged


# ---------------------------------------------------------------------------
# Core export — user-scoped table (normal: 1 file per user)
# ---------------------------------------------------------------------------

async def export_table_by_user(
    conn: asyncpg.Connection,
    table_name: str,
    user_column: str,
    base_dir: Path,
    now: datetime,
    user_name_map: dict[str, str],
    pk_cols: list[str] | None = None,
    batch_size: int = 5000,
) -> tuple[int, int]:
    """
    Export a user-scoped table into per-user JSON files.
    {base_dir}/YYYY/MM/DD/{user_name}/{table}.json

    If pk_cols is provided, updated records replace old ones (upsert).

    Returns (total_records_in_files, newly_added_or_updated).
    """
    hs_path = _hashset_path(base_dir, table_name)
    known_hashes = _load_hashset(hs_path)

    new_by_folder: dict[str, list[dict]] = defaultdict(list)
    new_hashes: list[str] = []

    query = f"SELECT * FROM {_quote_ident(table_name)}"

    async with conn.transaction():
        cur = await conn.cursor(query)
        while True:
            rows = await cur.fetch(batch_size)
            if not rows:
                break
            for row in rows:
                record = dict(row)
                h = _record_hash(record)
                if h not in known_hashes:
                    known_hashes.add(h)
                    new_hashes.append(h)
                    uid = str(record.get(user_column, "_unknown"))
                    folder = user_name_map.get(uid, uid)
                    new_by_folder[folder].append(record)

    if new_hashes:
        _append_hashset(hs_path, new_hashes)

    total_changed = 0
    total_in_files = 0
    for folder, new_records in new_by_folder.items():
        output_file = _build_user_output_path(base_dir, table_name, folder, now)
        existing = _load_existing_records(output_file)
        merged = _merge_with_upsert(existing, new_records, pk_cols)
        _write_json(output_file, merged)
        total_changed += len(new_records)
        total_in_files += len(merged)

    return total_in_files, total_changed


# ---------------------------------------------------------------------------
# Core export — user-scoped + conversation-scoped (messages)
# ---------------------------------------------------------------------------

async def export_table_by_user_and_conversation(
    conn: asyncpg.Connection,
    table_name: str,
    user_column: str,
    conv_column: str,
    base_dir: Path,
    now: datetime,
    user_name_map: dict[str, str],
    pk_cols: list[str] | None = None,
    batch_size: int = 5000,
) -> tuple[int, int]:
    """
    Export a table (e.g. messages) split by user AND conversation.
    {base_dir}/YYYY/MM/DD/{user_name}/{conversation_id}.json

    Each file contains messages for that conversation, sorted by created_at.
    If pk_cols is provided, updated records replace old ones (upsert).

    Returns (total_records_in_files, newly_added_or_updated).
    """
    hs_path = _hashset_path(base_dir, table_name)
    known_hashes = _load_hashset(hs_path)

    # Key: (user_folder, conv_id) → list of new records
    new_by_key: dict[tuple[str, str], list[dict]] = defaultdict(list)
    new_hashes: list[str] = []

    query = f"SELECT * FROM {_quote_ident(table_name)}"

    async with conn.transaction():
        cur = await conn.cursor(query)
        while True:
            rows = await cur.fetch(batch_size)
            if not rows:
                break
            for row in rows:
                record = dict(row)
                h = _record_hash(record)
                if h not in known_hashes:
                    known_hashes.add(h)
                    new_hashes.append(h)
                    uid = str(record.get(user_column, "_unknown"))
                    conv_id = str(record.get(conv_column, "_no_conv"))
                    folder = user_name_map.get(uid, uid)
                    new_by_key[(folder, conv_id)].append(record)

    if new_hashes:
        _append_hashset(hs_path, new_hashes)

    total_changed = 0
    total_in_files = 0
    for (folder, conv_id), new_records in new_by_key.items():
        user_dir = (
            base_dir
            / now.strftime("%Y")
            / now.strftime("%m")
            / now.strftime("%d")
            / folder
        )
        user_dir.mkdir(parents=True, exist_ok=True)
        output_file = user_dir / f"{conv_id}.json"

        existing = _load_existing_records(output_file)
        merged = _merge_with_upsert(existing, new_records, pk_cols)

        # Sort by created_at so messages read in chronological order
        merged.sort(key=lambda r: r.get("created_at", ""))

        _write_json(output_file, merged)
        total_changed += len(new_records)
        total_in_files += len(merged)

    return total_in_files, total_changed


# ---------------------------------------------------------------------------
# Core export — global table (no user column)
# ---------------------------------------------------------------------------

async def export_table_global(
    conn: asyncpg.Connection,
    table_name: str,
    base_dir: Path,
    now: datetime,
    pk_cols: list[str] | None = None,
    batch_size: int = 5000,
) -> tuple[int, int]:
    """
    Export a global table (e.g. 'users') into a single flat JSON file.
    If pk_cols is provided, updated records replace old ones (upsert).

    Returns (total_in_file, newly_added_or_updated).
    """
    hs_path = _hashset_path(base_dir, table_name)
    known_hashes = _load_hashset(hs_path)

    output_file = _build_global_output_path(base_dir, table_name, now)
    existing_records = _load_existing_records(output_file)

    new_records: list[dict] = []
    new_hashes: list[str] = []

    query = f"SELECT * FROM {_quote_ident(table_name)}"

    async with conn.transaction():
        cur = await conn.cursor(query)
        while True:
            rows = await cur.fetch(batch_size)
            if not rows:
                break
            for row in rows:
                record = dict(row)
                h = _record_hash(record)
                if h not in known_hashes:
                    known_hashes.add(h)
                    new_hashes.append(h)
                    new_records.append(record)

    if new_hashes:
        _append_hashset(hs_path, new_hashes)

    if new_records:
        merged = _merge_with_upsert(existing_records, new_records, pk_cols)
        _write_json(output_file, merged)
    else:
        merged = existing_records

    return len(merged), len(new_records)


# ---------------------------------------------------------------------------
# Single export cycle
# ---------------------------------------------------------------------------

async def run_export_cycle(
    db_url: str,
    tables: list[str],
    base_dir: Path,
    batch_size: int,
    schema_cache: dict[str, TableSchema] | None = None,
    user_name_map: dict[str, str] | None = None,
) -> tuple[dict[str, TableSchema], dict[str, str]]:
    """
    Run one full export cycle.
    Returns (schema_cache, user_name_map) for reuse.
    """
    now = datetime.now()
    logger.info("=== Export cycle started at %s ===", now.strftime("%Y-%m-%d %H:%M:%S"))

    try:
        conn = await asyncpg.connect(db_url)
    except Exception as exc:
        logger.error("Database connection failed: %s", exc)
        return schema_cache or {}, user_name_map or {}

    try:
        # Detect schema + user names once, then reuse
        if schema_cache is None:
            logger.info("Detecting schema (first run)...")
            schema_cache = await detect_schema_mapping(conn, tables)
        if user_name_map is None:
            user_name_map = await build_user_name_map(conn)

        total_new = 0
        for table in tables:
            info = schema_cache.get(table, TableSchema())
            try:
                pk = info.primary_keys
                if info.user_column and info.conversation_column:
                    total, added = await export_table_by_user_and_conversation(
                        conn, table, info.user_column, info.conversation_column,
                        base_dir, now, user_name_map, pk, batch_size,
                    )
                elif info.user_column:
                    total, added = await export_table_by_user(
                        conn, table, info.user_column, base_dir, now,
                        user_name_map, pk, batch_size,
                    )
                else:
                    total, added = await export_table_global(
                        conn, table, base_dir, now, pk, batch_size
                    )

                if added:
                    logger.info(
                        "  [%s] +%d new records (total %d)",
                        table, added, total,
                    )
                else:
                    logger.info("  [%s] no new records", table)
                total_new += added
            except Exception as exc:
                logger.error("  [%s] export failed: %s", table, exc)

        logger.info("=== Cycle done — %d new records across all tables ===", total_new)
    finally:
        await conn.close()

    return schema_cache, user_name_map


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

async def run_scheduler(
    db_url: str,
    tables: list[str],
    base_dir: Path,
    interval_minutes: int,
    batch_size: int,
) -> None:
    """Run export cycles in a loop."""
    stop_event = asyncio.Event()

    def _handle_signal():
        logger.info("Shutdown signal received — finishing current cycle...")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    logger.info(
        "Scheduler started — exporting every %d minutes. Press Ctrl+C to stop.",
        interval_minutes,
    )

    schema_cache = None
    user_name_map = None

    while not stop_event.is_set():
        schema_cache, user_name_map = await run_export_cycle(
            db_url, tables, base_dir, batch_size, schema_cache, user_name_map
        )

        try:
            await asyncio.wait_for(
                stop_event.wait(), timeout=interval_minutes * 1
            )
        except asyncio.TimeoutError:
            pass

    logger.info("Scheduler stopped.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Continuous PostgreSQL → JSON exporter (incremental, per-user)",
    )
    parser.add_argument(
        "--tables",
        type=str,
        default="conversations,messages,feedback,user_health_facts,users",
        help="Comma-separated table names (default: %(default)s)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=os.getenv(
            "EXPORT_OUTPUT_DIR",
            "/workspace/duynt/Refined_Chatbot/data/database_exports",
        ),
        help="Base output directory (default: $EXPORT_OUTPUT_DIR)",
    )
    parser.add_argument(
        "--db-url",
        type=str,
        default=os.getenv(
            "DATABASE_URL",
            "postgresql://admin:123456@localhost:5432/mydb",
        ),
        help="PostgreSQL connection URL (default: $DATABASE_URL)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=int(os.getenv("EXPORT_INTERVAL", "30")),
        help="Minutes between export cycles (default: 30)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=5000,
        help="Rows per cursor fetch batch (default: 5000)",
    )
    parser.add_argument(
        "--run-once",
        action="store_true",
        help="Run a single export and exit (no loop)",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()

    tables = [t.strip() for t in args.tables.split(",") if t.strip()]
    base_dir = Path(args.output_dir)
    base_dir.mkdir(parents=True, exist_ok=True)

    if args.run_once:
        await run_export_cycle(args.db_url, tables, base_dir, args.batch_size)
    else:
        await run_scheduler(
            args.db_url, tables, base_dir, args.interval, args.batch_size
        )


if __name__ == "__main__":
    asyncio.run(main())
