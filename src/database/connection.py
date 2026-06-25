"""
LeadCapture AI — Database Connection Module
Manages SQLite connection, auto-creates schema on first run,
and provides async helpers for common operations.
"""

import sqlite3
import os
import asyncio
from functools import lru_cache
from pathlib import Path
from src.config import settings, logger

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")


def get_db_path() -> str:
    """Return the database path, ensuring directory exists."""
    db_path = settings.DATABASE_PATH
    db_dir = os.path.dirname(db_path)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
    return db_path


def get_connection() -> sqlite3.Connection:
    """Get a synchronous SQLite connection with Row factory."""
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db() -> None:
    """Initialize database schema. Safe to call multiple times."""
    conn = get_connection()
    try:
        with open(SCHEMA_PATH, "r") as f:
            schema_sql = f.read()
        conn.executescript(schema_sql)
        conn.commit()
        logger.info("Database initialized successfully at %s", get_db_path())
    except Exception as e:
        logger.error("Failed to initialize database: %s", e)
        raise
    finally:
        conn.close()


def execute_query(query: str, params: tuple = ()) -> list[dict]:
    """Execute a query and return results as list of dicts."""
    conn = get_connection()
    try:
        cursor = conn.execute(query, params)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error("Query error: %s | Query: %s", e, query[:100])
        raise
    finally:
        conn.close()


def execute_write(query: str, params: tuple = ()) -> int:
    """Execute an INSERT/UPDATE/DELETE and return lastrowid."""
    conn = get_connection()
    try:
        cursor = conn.execute(query, params)
        conn.commit()
        return cursor.lastrowid
    except Exception as e:
        logger.error("Write error: %s | Query: %s", e, query[:100])
        raise
    finally:
        conn.close()


def execute_write_many(query: str, params_list: list[tuple]) -> int:
    """Execute a write with multiple parameter sets."""
    conn = get_connection()
    try:
        cursor = conn.executemany(query, params_list)
        conn.commit()
        return cursor.rowcount
    except Exception as e:
        logger.error("Batch write error: %s", e)
        raise
    finally:
        conn.close()
