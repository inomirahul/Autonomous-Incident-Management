# servers/file_editor_mcp.py
import os
from pathlib import Path
from typing import Dict, Any, Optional
from fastmcp import FastMCP
from filelock import FileLock, Timeout

mcp = FastMCP("file-editor")
LOCK_DIR = Path(os.getenv("FILE_LOCK_DIR", "/tmp/fe_locks"))
LOCK_DIR.mkdir(parents=True, exist_ok=True)

# Default limits to prevent token overflow when sending to LLM
DEFAULT_MAX_LINES = 200
DEFAULT_MAX_CHARS = 8000


def _lock_path(path: str) -> str:
    # deterministic lock file per path
    safe = Path(path).absolute().as_posix().replace("/", "_")
    return str(LOCK_DIR / f"{safe}.lock")


def _truncate_content(
    text: str,
    max_lines: Optional[int] = None,
    max_chars: Optional[int] = None,
    start_line: int = 1
) -> tuple[str, dict]:
    """
    Truncate file content by lines and/or characters.
    Returns (truncated_text, metadata_dict).
    start_line is 1-indexed.
    """
    lines = text.splitlines(keepends=True)
    total_lines = len(lines)
    total_chars = len(text)

    # Apply line range (convert to 0-indexed)
    start_idx = max(0, start_line - 1)
    lines = lines[start_idx:]

    # Apply max_lines limit
    truncated_lines = False
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        truncated_lines = True

    result = "".join(lines)

    # Apply max_chars limit
    truncated_chars = False
    if max_chars and len(result) > max_chars:
        result = result[:max_chars]
        truncated_chars = True

    metadata = {
        "total_lines": total_lines,
        "total_chars": total_chars,
        "returned_lines": len(result.splitlines()),
        "returned_chars": len(result),
        "truncated": truncated_lines or truncated_chars,
        "start_line": start_line,
    }

    if truncated_lines or truncated_chars:
        result += f"\n\n...[TRUNCATED: file has {total_lines} lines, {total_chars} chars. Use start_line/max_lines to read specific sections.]"

    return result, metadata


@mcp.tool()
def read_file(
    path: str,
    encoding: str = "utf-8",
    max_lines: Optional[int] = DEFAULT_MAX_LINES,
    max_chars: Optional[int] = DEFAULT_MAX_CHARS,
    start_line: int = 1
) -> Dict[str, Any]:
    """
    Read a file with optional truncation to prevent token overflow.

    Args:
        path: File path to read
        encoding: File encoding (default: utf-8)
        max_lines: Maximum lines to return (default: 200, use None for no limit)
        max_chars: Maximum characters to return (default: 8000, use None for no limit)
        start_line: 1-indexed line to start reading from (default: 1)

    Returns:
        Dict with ok, path, content, and truncation metadata
    """
    p = Path(path)
    if not p.exists():
        return {"ok": False, "error": "not_found", "path": path}
    try:
        text = p.read_text(encoding=encoding, errors="ignore")
        content, metadata = _truncate_content(text, max_lines, max_chars, start_line)
        return {"ok": True, "path": str(p), "content": content, **metadata}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@mcp.tool()
def write_file(path: str, content: str, encoding: str = "utf-8", overwrite: bool = True, timeout: float = 5.0) -> Dict[str, Any]:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(_lock_path(path))
    try:
        with lock.acquire(timeout=timeout):
            if p.exists() and not overwrite:
                return {"ok": False, "error": "exists", "path": path}
            p.write_text(content, encoding=encoding)
            return {"ok": True, "path": str(p)}
    except Timeout:
        return {"ok": False, "error": "lock_timeout"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@mcp.tool()
def append_file(path: str, content: str, encoding: str = "utf-8", timeout: float = 5.0) -> Dict[str, Any]:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(_lock_path(path))
    try:
        with lock.acquire(timeout=timeout):
            with p.open("a", encoding=encoding) as f:
                f.write(content)
            return {"ok": True, "path": str(p)}
    except Timeout:
        return {"ok": False, "error": "lock_timeout"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@mcp.tool()
def replace_in_file(path: str, pattern: str, replacement: str, regex_flags: int = 0, timeout: float = 5.0) -> Dict[str, Any]:
    """
    Replace all matches of pattern (regex) with replacement in file.
    Returns how many replacements were made.
    """
    import re
    p = Path(path)
    if not p.exists():
        return {"ok": False, "error": "not_found", "path": path}
    lock = FileLock(_lock_path(path))
    try:
        with lock.acquire(timeout=timeout):
            text = p.read_text(encoding="utf-8', errors='ignore")
            new_text, n = re.subn(pattern, replacement, text, flags=regex_flags)
            if n == 0:
                return {"ok": True, "replacements": 0}
            p.write_text(new_text, encoding="utf-8")
            return {"ok": True, "replacements": n}
    except Timeout:
        return {"ok": False, "error": "lock_timeout"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@mcp.tool()
def move_file(src: str, dst: str, overwrite: bool = False) -> Dict[str, Any]:
    s = Path(src)
    d = Path(dst)
    if not s.exists():
        return {"ok": False, "error": "not_found", "path": src}
    if d.exists() and not overwrite:
        return {"ok": False, "error": "exists", "path": dst}
    d.parent.mkdir(parents=True, exist_ok=True)
    s.replace(d)
    return {"ok": True, "from": str(s), "to": str(d)}

# @mcp.tool()
# def delete_file(path: str) -> Dict[str, Any]:
#     p = Path(path)
#     if not p.exists():
#         return {"ok": False, "error": "not_found"}
#     p.unlink()
#     return {"ok": True, "path": str(p)}

if __name__ == "__main__":
        mcp.run(
        transport="http",
        host="0.0.0.0",
        port=8006
    )
