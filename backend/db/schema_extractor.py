# Extracts schema using information_schema
import logging
from typing import Any
import asyncpg
from backend.db.connection import get_pool

logger = logging.getLogger(__name__)


# ── Queries against information_schema ───────────────────────

_TABLES_QUERY = """
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = 'public'
      AND table_type   = 'BASE TABLE'
    ORDER BY table_name;
"""

_COLUMNS_QUERY = """
    SELECT
        column_name,
        data_type,
        is_nullable,
        column_default
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name   = $1
    ORDER BY ordinal_position;
"""

_FOREIGN_KEYS_QUERY = """
    SELECT
        kcu.column_name         AS from_column,
        ccu.table_name          AS to_table,
        ccu.column_name         AS to_column
    FROM information_schema.table_constraints        AS tc
    JOIN information_schema.key_column_usage         AS kcu
        ON tc.constraint_name = kcu.constraint_name
        AND tc.table_schema   = kcu.table_schema
    JOIN information_schema.constraint_column_usage  AS ccu
        ON ccu.constraint_name = tc.constraint_name
        AND ccu.table_schema   = tc.table_schema
    WHERE tc.constraint_type = 'FOREIGN KEY'
      AND tc.table_schema    = 'public'
      AND tc.table_name      = $1;
"""

_PRIMARY_KEYS_QUERY = """
    SELECT kcu.column_name
    FROM information_schema.table_constraints        AS tc
    JOIN information_schema.key_column_usage         AS kcu
        ON tc.constraint_name = kcu.constraint_name
        AND tc.table_schema   = kcu.table_schema
    WHERE tc.constraint_type = 'PRIMARY KEY'
      AND tc.table_schema    = 'public'
      AND tc.table_name      = $1;
"""


# ── Main extractor ────────────────────────────────────────────

async def extract_schema(pool: asyncpg.Pool | None = None) -> dict[str, Any]:
    """
    Connects to the database and extracts the full public schema.

    Returns a structured dict:
    {
        "tables": {
            "members": {
                "columns": [
                    {
                        "name":         "member_id",
                        "type":         "integer",
                        "nullable":     False,
                        "default":      "nextval(...)",
                        "primary_key":  True
                    },
                    ...
                ],
                "foreign_keys": [
                    {
                        "from_column":  "book_id",
                        "to_table":     "books",
                        "to_column":    "book_id"
                    },
                    ...
                ]
            },
            ...
        }
    }
    """
    conn_pool = pool or await get_pool()
    schema: dict[str, Any] = {"tables": {}}

    async with conn_pool.acquire() as conn:

        # 1. Get all table names in public schema
        tables = await conn.fetch(_TABLES_QUERY)
        logger.info(f"Found {len(tables)} tables in public schema.")

        for table_row in tables:
            table_name = table_row["table_name"]

            # 2. Get columns for this table
            columns_raw = await conn.fetch(_COLUMNS_QUERY, table_name)

            # 3. Get primary key columns
            pk_rows   = await conn.fetch(_PRIMARY_KEYS_QUERY, table_name)
            pk_cols   = {row["column_name"] for row in pk_rows}

            # 4. Get foreign keys for this table
            fk_rows   = await conn.fetch(_FOREIGN_KEYS_QUERY, table_name)

            columns = [
                {
                    "name":        col["column_name"],
                    "type":        col["data_type"],
                    "nullable":    col["is_nullable"] == "YES",
                    "default":     col["column_default"],
                    "primary_key": col["column_name"] in pk_cols,
                }
                for col in columns_raw
            ]

            foreign_keys = [
                {
                    "from_column": fk["from_column"],
                    "to_table":    fk["to_table"],
                    "to_column":   fk["to_column"],
                }
                for fk in fk_rows
            ]

            schema["tables"][table_name] = {
                "columns":      columns,
                "foreign_keys": foreign_keys,
            }

            logger.debug(
                f"Extracted table '{table_name}': "
                f"{len(columns)} columns, {len(foreign_keys)} FK(s)."
            )

    logger.info("Schema extraction complete.")
    return schema


def format_schema_for_prompt(schema: dict[str, Any]) -> str:
    """
    Converts the extracted schema dict into a clean,
    LLM-readable text block to inject into prompts.

    Example output:
        Table: members
          - member_id (integer, PK, NOT NULL)
          - name (character varying, NOT NULL)
          - email (character varying, NOT NULL)
          - city (character varying, NOT NULL)
          - joined_date (date, NOT NULL)
          FK: member_id → members.member_id

        Table: borrowings
          ...
    """
    lines = []

    for table_name, table_info in schema["tables"].items():
        lines.append(f"Table: {table_name}")

        for col in table_info["columns"]:
            parts = [col["type"]]
            if col["primary_key"]:
                parts.append("PK")
            if not col["nullable"]:
                parts.append("NOT NULL")
            if col["default"]:
                parts.append(f"DEFAULT {col['default']}")
            lines.append(f"  - {col['name']} ({', '.join(parts)})")

        for fk in table_info["foreign_keys"]:
            lines.append(
                f"  FK: {fk['from_column']} → {fk['to_table']}.{fk['to_column']}"
            )

        lines.append("")   # blank line between tables

    return "\n".join(lines).strip()