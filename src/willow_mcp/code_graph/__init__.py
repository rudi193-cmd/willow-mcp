"""code_graph — a budget-aware Python/JS symbol graph over a local SQLite DB.

Ported verbatim from willow-2.0's `sap/code_graph` (the top 🟢 item on the
migration shortlist, docs/migrations/willow-2.0-gap-inventory.md §6): the only
call-graph capability willow-mcp lacked, and a self-contained one — stdlib `ast`
+ `sqlite3` + `re`, no Postgres, no network, no external CLI. `index_repo` walks
a repo into `symbols`/`edges`/`indexed_files` tables; the readers answer
callers/callees (`explain_symbol`), blast radius (`analyze_impact`), a
token-budgeted context walk (`walk`), fuzzy symbol search, and task→file
suggestion.

The three core modules import nothing but the standard library — the willow-2.0
version's only non-stdlib coupling lived in its MCP wrapper and CLI, which are
re-implemented here as willow-mcp tools rather than carried over.
"""
from .fuzzy import explain_symbol, search_symbols, suggest_files
from .indexer import index_repo
from .walker import analyze_impact, walk

__all__ = [
    "index_repo",
    "walk",
    "analyze_impact",
    "search_symbols",
    "explain_symbol",
    "suggest_files",
]
