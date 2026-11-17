"""Tools for the NBA Clutch Agent: read-only SQL over DuckDB + the offline-built context docs."""
import json
import os
import re
import threading
from pathlib import Path

import duckdb

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
CTX_DIR = ROOT / "context"

MAX_ROWS = 200            # rows returned to the model per query
MAX_RESULT_CHARS = 30_000  # hard cap on the size of one tool result
QUERY_TIMEOUT_S = 60

# --- Database: in-memory DuckDB over the Parquet files, with the helper views ---

_con = duckdb.connect()
_con.execute(f"SET memory_limit='{os.environ.get('DUCKDB_MEMORY', '1500MB')}'")
_con.execute((CTX_DIR / "views.sql").read_text().replace("{DATA}", str(DATA_DIR)))
VIEW_NAMES = [r[0] for r in _con.execute(
    "SELECT view_name FROM duckdb_views() WHERE NOT internal ORDER BY 1").fetchall()]

# Functions that could read arbitrary files or the environment.
_FORBIDDEN = re.compile(r"\b(read_\w+|\w+_scan|glob|getenv|current_setting|duckdb_\w+|pragma_\w+)\s*\(", re.I)


def _check_query(query: str) -> str | None:
    """Return an error message if the query is not a single read-only SELECT, else None."""
    try:
        statements = duckdb.extract_statements(query)
    except Exception as e:  # syntax error that stops parsing
        return f"SQL syntax error: {e}"
    if len(statements) != 1:
        return "Send exactly one SQL statement per call."
    if statements[0].type != duckdb.StatementType.SELECT:
        return "Only read-only SELECT queries (including WITH ... SELECT) are allowed."
    if _FORBIDDEN.search(query):
        return "File/system functions are not allowed. Query the provided tables and views only."
    return None


def run_sql(query: str) -> str:
    """Run one read-only query. Returns JSON: {columns, rows, row_count, truncated} or {error, hint}."""
    hint = f"Available tables/views: {', '.join(VIEW_NAMES)}. Call get_context('schema') for exact column names."
    return _execute(_con, query, hint)


def _execute(con, query: str, error_hint: str | None) -> str:
    query = (query or "").strip()
    if not query:
        return json.dumps({"error": "Empty query."})
    problem = _check_query(query)
    if problem:
        return json.dumps({"error": problem})

    cur = con.cursor()
    timer = threading.Timer(QUERY_TIMEOUT_S, cur.interrupt)
    timer.start()
    try:
        cur.execute(query)
        columns = [d[0] for d in cur.description]
        rows = cur.fetchmany(MAX_ROWS + 1)
    except duckdb.InterruptException:
        return json.dumps({"error": f"Query timed out after {QUERY_TIMEOUT_S}s.",
                           "hint": "Filter by season/season_type first, aggregate earlier, or avoid joining plays to itself."})
    except Exception as e:
        err = {"error": f"{type(e).__name__}: {e}"}
        if error_hint:
            err["hint"] = error_hint
        return json.dumps(err)
    finally:
        timer.cancel()
        cur.close()

    truncated = len(rows) > MAX_ROWS
    # NaN/Infinity are not valid JSON: turn them into NULL so results parse in the browser and in the model request.
    rows = [[None if isinstance(v, float) and (v != v or v in (float("inf"), float("-inf"))) else v for v in r]
            for r in rows[:MAX_ROWS]]
    result = {"columns": columns, "rows": rows, "row_count": len(rows), "truncated": truncated}
    text = json.dumps(result, default=str)
    while len(text) > MAX_RESULT_CHARS and rows:  # keep the result a manageable size
        rows = rows[: len(rows) // 2]
        result.update(rows=rows, row_count=len(rows), truncated=True)
        text = json.dumps(result, default=str)
    if truncated:
        result["note"] = f"Only the first {len(rows)} rows are shown; aggregate or add LIMIT/ORDER BY."
        text = json.dumps(result, default=str)
    return text


# --- Context docs built offline by build/build_context.py ---

_TOPICS = {"schema": "schema.md", "glossary": "glossary.md", "teams": "teams.md", "examples": "examples.md"}


def get_context(topic: str) -> str:
    name = _TOPICS.get(topic)
    if not name:
        return json.dumps({"error": f"Unknown topic '{topic}'. Choose from: {', '.join(_TOPICS)}"})
    return (CTX_DIR / name).read_text()


def prompt_context() -> str:
    """Schema + glossary text that goes straight into the system prompt."""
    return (CTX_DIR / "schema.md").read_text() + "\n" + (CTX_DIR / "glossary.md").read_text()


_EXAMPLES = json.loads((CTX_DIR / "examples.json").read_text())
_STOP = {"the", "a", "an", "of", "in", "to", "and", "or", "is", "are", "do", "does", "how", "what", "which", "who", "for", "by", "from", "with", "on"}


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOP and len(w) > 1}


def search_examples(query: str) -> str:
    """Return the 3 verified question->SQL examples closest to the query (keyword overlap)."""
    q = _tokens(query)
    scored = []
    for e in _EXAMPLES:
        doc = _tokens(f"{e['question']} {e['topic']} {e['id'].replace('_', ' ')}")
        scored.append((len(q & doc) + 0.2 * len(q & _tokens(e["sql"])), e))
    scored.sort(key=lambda x: -x[0])
    top = [{"id": e["id"], "question": e["question"], "sql": e["sql"]} for s, e in scored[:3]]
    return json.dumps({"examples": top})


# --- Tool definitions for the LLM ---

TOOLS = [
    {"type": "function", "function": {
        "name": "run_sql",
        "description": ("Run ONE read-only DuckDB SQL query (SELECT / WITH) over the NBA play-by-play views and return "
                        f"up to {MAX_ROWS} rows as JSON. Query the helper views (plays, clutch_plays, games, game_swings, "
                        "player_shooting, team_game_clutch, ...), not raw files. Always run a query before stating a number."),
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "A single DuckDB SQL SELECT statement."}},
            "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "get_context",
        "description": ("Read reference docs: 'schema' (all views and columns), 'glossary' (conventions, clutch definition, "
                        "event codes, data limits), 'teams' (team abbreviations), or 'examples' (all verified queries)."),
        "parameters": {"type": "object", "properties": {
            "topic": {"type": "string", "enum": list(_TOPICS)}}, "required": ["topic"]}}},
    {"type": "function", "function": {
        "name": "search_examples",
        "description": "Find the 3 verified example questions with working SQL most similar to your question. Use before writing a complex query.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "The user's question or topic in plain words."}},
            "required": ["query"]}}},
]

# --- Plain baseline: run_sql only, over the RAW tables (original names/columns, no helper views, no docs) ---

_plain_con = duckdb.connect()
_plain_con.execute(f"SET memory_limit='{os.environ.get('DUCKDB_MEMORY', '1500MB')}'")
_plain_con.execute(f"""
CREATE VIEW play_by_play AS SELECT * FROM read_parquet('{DATA_DIR}/play_by_play_*.parquet');
CREATE VIEW game AS SELECT * FROM read_parquet('{DATA_DIR}/game.parquet');
CREATE VIEW other_stats AS SELECT * FROM read_parquet('{DATA_DIR}/other_stats.parquet');
CREATE VIEW line_score AS SELECT * FROM read_parquet('{DATA_DIR}/line_score.parquet');
CREATE VIEW officials AS SELECT * FROM read_parquet('{DATA_DIR}/officials.parquet');
CREATE VIEW team AS SELECT * FROM read_parquet('{DATA_DIR}/team.parquet');
CREATE VIEW team_history AS SELECT * FROM read_parquet('{DATA_DIR}/team_history.parquet');
CREATE VIEW player AS SELECT * FROM read_parquet('{DATA_DIR}/player.parquet');
""")


def run_sql_plain(query: str) -> str:
    return _execute(_plain_con, query, None)


TOOLS_PLAIN = [{"type": "function", "function": {
    "name": "run_sql",
    "description": "Run one read-only SQL query (DuckDB) against the NBA database and return up to 200 rows as JSON.",
    "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}}]


def run_tool_plain(name: str, args: dict) -> str:
    if name != "run_sql":
        return json.dumps({"error": f"Unknown tool '{name}'."})
    try:
        return run_sql_plain(**args)
    except TypeError as e:
        return json.dumps({"error": f"Bad arguments for {name}: {e}"})


_IMPL = {"run_sql": run_sql, "get_context": get_context, "search_examples": search_examples}


def run_tool(name: str, args: dict) -> str:
    fn = _IMPL.get(name)
    if fn is None:
        return json.dumps({"error": f"Unknown tool '{name}'."})
    try:
        return fn(**args)
    except TypeError as e:
        return json.dumps({"error": f"Bad arguments for {name}: {e}"})
