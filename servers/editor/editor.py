# servers/file_editor_mcp.py
import os
from pathlib import Path
from typing import Dict, Any
from fastmcp import FastMCP
from filelock import FileLock, Timeout

mcp = FastMCP("file-editor")
LOCK_DIR = Path(os.getenv("FILE_LOCK_DIR", "/tmp/fe_locks"))
LOCK_DIR.mkdir(parents=True, exist_ok=True)

def _lock_path(path: str) -> str:
    # deterministic lock file per path
    safe = Path(path).absolute().as_posix().replace("/", "_")
    return str(LOCK_DIR / f"{safe}.lock")

@mcp.tool()
def read_file_excerpt(
    path: str, 
    start_line: int = 1, 
    end_line: int | None = None,
    max_lines: int = 50
) -> Dict[str, Any]:
    """Read only specific lines from a file to minimize context."""
    p = Path(path)
    if not p.exists():
        return {"ok": False, "error": "not_found"}
    
    try:
        lines = p.read_text(encoding="utf-8", errors="ignore").split('\n')
        
        if end_line is None:
            end_line = min(start_line + max_lines, len(lines))
        
        excerpt = '\n'.join(lines[start_line-1:end_line])
        
        return {
            "ok": True,
            "path": path,
            "excerpt": excerpt,
            "line_range": f"{start_line}-{end_line}",
            "total_lines": len(lines)
        }
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
