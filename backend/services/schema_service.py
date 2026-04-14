# Handles schema extraction, caching, refresh
import logging
from typing import Any, Optional

from backend.cache.schema_cache import (
    get_schema,
    get_schema_prompt_text,
    get_cache_info,
    refresh_schema,
    clear_cache,
)
from backend.models.response import SchemaResponse, SchemaTableInfo

logger = logging.getLogger(__name__)


class SchemaService:
    """
    Public facade over schema extraction + caching.

    All other services and routes talk to SchemaService —
    never directly to schema_extractor or schema_cache.
    This keeps the cache internals hidden behind one clean interface.

    Responsibilities:
      - Serve schema for prompt injection  (NLToSQLService)
      - Serve schema metadata for the API  (GET /schema)
      - Trigger manual refresh             (POST /schema/refresh)
      - Clear schema on session reset      (custom mode)
    """

    def __init__(self, database_url: Optional[str] = None):
        self.database_url = database_url   # None = demo mode


    async def get_prompt_text(self) -> str:
        """
        Returns the LLM-ready schema string.
        Auto-refreshes from DB if cache is stale or empty.
        Called by NLToSQLService before every SQL generation.
        """
        text = await get_schema_prompt_text(self.database_url)
        if not text:
            raise RuntimeError(
                "Schema could not be loaded. "
                "Check your database connection and credentials."
            )
        return text


    async def get_schema_response(self) -> SchemaResponse:
        """
        Returns a structured SchemaResponse for GET /schema.
        Builds per-table metadata from the cached schema dict.
        """
        schema     = await get_schema(self.database_url)
        cache_info = get_cache_info(self.database_url)

        if not cache_info:
            raise RuntimeError("Schema cache is empty. Try refreshing.")

        tables: list[SchemaTableInfo] = []

        for table_name, table_data in schema["tables"].items():
            columns      = table_data["columns"]
            foreign_keys = table_data["foreign_keys"]

            primary_keys = [
                col["name"] for col in columns if col.get("primary_key")
            ]
            column_names = [col["name"] for col in columns]
            fk_strings   = [
                f"{fk['from_column']} → {fk['to_table']}.{fk['to_column']}"
                for fk in foreign_keys
            ]

            tables.append(SchemaTableInfo(
                table_name   = table_name,
                column_count = len(columns),
                columns      = column_names,
                primary_keys = primary_keys,
                foreign_keys = fk_strings,
            ))

        return SchemaResponse(
            table_count = len(tables),
            tables      = tables,
            version     = cache_info["version"],
            cached_at   = cache_info["cached_at"],
            expires_in  = cache_info["expires_in"],
            fingerprint = cache_info["fingerprint"],
        )


    async def refresh(self) -> dict[str, Any]:
        """
        Forces a schema re-extraction from the DB.
        Returns summary info about what changed.
        Called by POST /schema/refresh.
        """
        logger.info(f"Manual schema refresh triggered.")

        old_info = get_cache_info(self.database_url)
        old_fp   = old_info["fingerprint"] if old_info else None

        await refresh_schema(self.database_url)

        new_info = get_cache_info(self.database_url)

        changed = old_fp != new_info["fingerprint"]

        logger.info(
            f"Schema refresh complete — "
            f"{'changed' if changed else 'unchanged'}, "
            f"version {new_info['version']}."
        )

        return {
            "refreshed"  : True,
            "changed"    : changed,
            "version"    : new_info["version"],
            "fingerprint": new_info["fingerprint"],
            "table_count": new_info["table_count"],
        }


    def clear(self) -> None:
        """
        Clears the schema cache for this DB.
        Called on custom mode session reset so a
        returning user gets a fresh extraction.
        """
        clear_cache(self.database_url)
        logger.info("Schema cache cleared via SchemaService.")