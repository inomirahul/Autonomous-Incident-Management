# servers/indexer_mcp.py
import os
import logging
from pathlib import Path
from fastmcp import FastMCP
from whoosh import index
from whoosh.fields import Schema, TEXT, ID, KEYWORD
from whoosh.analysis import RegexTokenizer, LowercaseFilter
from whoosh.qparser import QueryParser
from whoosh.highlight import ContextFragmenter

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("whoosh_code_index")

# Config from env
INDEX_DIR = os.getenv("CODE_INDEX_DIR", "/code_index")
CODE_INDEX_REPOS = os.getenv("CODE_INDEX_REPOS")        # comma separated names
CODE_INDEX_PATHS = os.getenv("CODE_INDEX_PATHS")        # comma separated container paths
EXCLUDE_DIRS = {
    ".git", ".github", ".hg", ".svn",
    "venv", ".venv", "env", ".env",
    "__pycache__", "node_modules",
    "site-packages",
    "dist", "build",
    ".idea", ".vscode",
}
EXCLUDE_FILE_SUFFIXES = {
    ".pyc", ".pyo", ".log", ".lock", ".min.js",
}
EXTENSION_LANGUAGE_MAP = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".java": "java",
    ".html": "html",
    ".css": "css",
}

# Schema
code_analyzer = RegexTokenizer() | LowercaseFilter()
schema = Schema(
    repo=ID(stored=True),
    path=ID(stored=True, unique=True),
    filename=TEXT(stored=True),
    language=KEYWORD(stored=True, lowercase=True),
    content=TEXT(stored=True, analyzer=code_analyzer, phrase=True),
)

mcp = FastMCP("code-indexer")


def ensure_index():
    Path(INDEX_DIR).mkdir(parents=True, exist_ok=True)
    if not index.exists_in(INDEX_DIR):
        log.info("Creating Whoosh index in %s", INDEX_DIR)
        return index.create_in(INDEX_DIR, schema)
    else:
        log.info("Opening Whoosh index in %s", INDEX_DIR)
        return index.open_dir(INDEX_DIR)


IX = ensure_index()


def index_repo_impl(repo_name: str, root_path: str) -> dict:
    """
    Internal function: Walk root_path and index supported file types under repo_name.
    NOT exposed as an MCP tool; called only from startup or internal flows.
    """
    writer = IX.writer(limitmb=256)
    indexed = 0
    skipped_files = 0
    skipped_dirs = 0

    root_path = os.path.abspath(root_path)
    if not os.path.exists(root_path):
        log.warning("[%s] path does not exist, skipping: %s", repo_name, root_path)
        return {"indexed": 0, "skipped_files": 0, "skipped_dirs": 0, "skipped_reason": "path_missing"}

    for root, dirs, files in os.walk(root_path):
        original_dirs = list(dirs)
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        skipped_dirs += len(original_dirs) - len(dirs)

        for name in files:
            if any(name.endswith(s) for s in EXCLUDE_FILE_SUFFIXES):
                skipped_files += 1
                continue

            ext = os.path.splitext(name)[1]
            if ext not in EXTENSION_LANGUAGE_MAP:
                skipped_files += 1
                continue

            full_path = os.path.join(root, name)
            try:
                with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except Exception as e:
                log.warning("Read failed: %s (%s)", full_path, e)
                skipped_files += 1
                continue

            # path stored as repo:relative_path
            rel = os.path.relpath(full_path, root_path)
            writer.add_document(
                repo=repo_name,
                path=f"{repo_name}:{rel}",
                filename=name,
                language=EXTENSION_LANGUAGE_MAP[ext],
                content=content,
            )
            indexed += 1
            if indexed % 100 == 0:
                log.info("[%s] indexed %d files", repo_name, indexed)

    try:
        writer.commit()
    except Exception as e:
        log.exception("Whoosh writer.commit failed for %s: %s", repo_name, e)
        raise
    log.info("[%s] done | indexed=%d skipped_files=%d skipped_dirs=%d", repo_name, indexed, skipped_files, skipped_dirs)
    return {"indexed": indexed, "skipped_files": skipped_files, "skipped_dirs": skipped_dirs}


@mcp.tool()
def search_code(query_string: str, repo: str | None = None, limit: int = 10) -> list:
    log.info("search_code called | query=%r repo=%r limit=%d", query_string, repo, limit)
    ix = IX
    results_out = []

    with ix.searcher() as searcher:
        parser = QueryParser("content", schema=ix.schema)
        try:
            if repo:
                query_string = f'repo:"{repo}" AND ({query_string})'
            log.info("Final parsed query string: %s", query_string)
            query = parser.parse(query_string)
            log.info("Parsed query object: %r", query)
        except Exception:
            log.exception("Query parsing failed")
            return []

        results = searcher.search(query, limit=limit)
        log.info("Search executed | hits=%d", len(results))

        results.fragmenter = ContextFragmenter(maxchars=300, surround=50)

        for hit in results:
            snippet = hit.highlights("content")
            results_out.append({
                "repo": hit["repo"],
                "path": hit["path"],
                "filename": hit["filename"],
                "language": hit.get("language"),
                "snippet": snippet,
                "score": float(hit.score)
            })

    log.info("search_code completed | returned=%d", len(results_out))
    return results_out


@mcp.tool()
def list_indexed_repos() -> list:
    ix = IX
    repos = set()
    with ix.searcher() as s:
        for f in s.all_stored_fields():
            repos.add(f.get("repo"))
    return list(repos)


def parse_env_lists(repos_csv: str, paths_csv: str):
    repos = [r.strip() for r in repos_csv.split(",") if r.strip()]
    paths = [p.strip() for p in paths_csv.split(",") if p.strip()]
    if not repos or not paths:
        return []
    # pair up by index; drop mismatches beyond shortest list
    pairs = []
    count = min(len(repos), len(paths))
    for i in range(count):
        pairs.append((repos[i], paths[i]))
    if len(repos) != len(paths):
        log.warning("CODE_INDEX_REPOS and CODE_INDEX_PATHS length mismatch: using first %d pairs", count)
    return pairs


def run_index_all_from_env():
    pairs = parse_env_lists(CODE_INDEX_REPOS, CODE_INDEX_PATHS)
    if not pairs:
        log.info("No CODE_INDEX_REPOS/CODE_INDEX_PATHS provided; skipping auto-index.")
        return
    log.info("Auto-indexing %d repos from env", len(pairs))
    for repo_name, path in pairs:
        log.info("Indexing %s -> %s", repo_name, path)
        res = index_repo_impl(repo_name, path)
        log.info("Result for %s: %s", repo_name, res)


if __name__ == "__main__":
    run_index_all_from_env()
    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=8005
    )

