# backend/prompts/nl_to_sql.py
# Prompt builder for NL to SQL conversion
def build_nl_to_sql_prompt(
    question   : str,
    schema_text: str,
    history    : list[dict] | None = None,
) -> str:
    """
    Builds the prompt sent to Gemini to convert a natural
    language question into a PostgreSQL SELECT query.

    Args:
        question    : the user's current NL question
        schema_text : formatted schema from format_schema_for_prompt()
        history     : last N conversation turns, each a dict with
                      keys 'question' and 'sql'. None or [] = no history.
    """

    # ── Conversation history block (optional) ────────────────
    history_block = ""
    if history:
        lines = ["CONVERSATION HISTORY (most recent last):"]
        for turn in history:
            lines.append(f"  Q: {turn['question']}")
            lines.append(f"  SQL: {turn['sql']}")
        history_block = "\n".join(lines)

    return f"""You are an expert PostgreSQL query writer.

Your job is to convert the user's natural language question into 
a single valid PostgreSQL SELECT query using the schema below.

DATABASE SCHEMA:
{schema_text}

STRICT RULES — you must follow all of these:
1. Output ONLY the SQL query — no explanation, no markdown, no commentary.
2. Only use SELECT statements. Never use INSERT, UPDATE, DELETE, DROP, or ALTER.
3. Only reference tables and columns that exist in the schema above.
4. Always use explicit JOIN ... ON syntax. Never use implicit joins (comma-separated tables).
5. Use table aliases for clarity when joining multiple tables.
6. For text filters, always use partial matching: ILIKE '%value%' — never bare ILIKE 'value' unless the user explicitly asks for an exact match.
7. Always end the query with a semicolon.
8. If the question asks for "top N" or "most", use ORDER BY ... LIMIT N.
9. If a column could belong to multiple tables, qualify it with the table name or alias.
10. Never SELECT *  — always name the columns explicitly.

{history_block}

USER QUESTION:
{question}

SQL QUERY:
"""