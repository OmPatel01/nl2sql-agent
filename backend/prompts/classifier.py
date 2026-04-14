# Prompt template for query classification
def build_classifier_prompt(question: str, schema_text: str) -> str:
    """
    Builds the prompt sent to Gemini to classify whether
    a user's question is answerable from the database schema.

    Returns a prompt that instructs Gemini to respond with
    exactly one word: VALID or INVALID, plus a short reason.
    """

    return f"""You are a query classifier for a natural language to SQL system.

Your job is to decide if the user's question can be answered using 
the database schema provided below.

DATABASE SCHEMA:
{schema_text}

RULES:
- Reply VALID if the question is clearly about data in the schema above.
- Reply INVALID if the question is:
    - Unrelated to the database (e.g. general knowledge, math, coding help)
    - About modifying data (insert, update, delete, drop)
    - Completely ambiguous with no relation to any table or column
    - A greeting or small talk

FORMAT — respond in exactly this format, nothing else:
CLASSIFICATION: VALID or INVALID
REASON: one short sentence explaining why

USER QUESTION:
{question}
"""