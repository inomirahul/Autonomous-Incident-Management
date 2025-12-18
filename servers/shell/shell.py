import os
import shlex
import subprocess
import re
import logging
from typing import List, Dict, Any
from fastmcp import FastMCP

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("whoosh_code_index")

# ---------------------------------------------------------------------------

mcp = FastMCP("shell-tools")

# Output truncation limits to prevent token overflow
MAX_STDOUT_CHARS = 4000
MAX_STDERR_CHARS = 2000


def _truncate_output(text: str, max_chars: int, label: str = "output") -> str:
    """Truncate output and add indicator if truncated."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n...[{label} TRUNCATED: {len(text)} chars total, showing first {max_chars}]"


def _run_shell(cmd: str, cwd: str | None = None, timeout: int = 30) -> Dict[str, Any]:
    """Run a shell command and return a structured result while logging each step.

    Returns the same structured dict as before, but logs input arguments, subprocess
    invocation details and truncated outputs for visibility.
    Output is truncated to prevent token overflow when sent to LLM.
    """
    logger.info("_run_shell called: cmd=%r, cwd=%r, timeout=%s", cmd, cwd, timeout)
    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        # Log key parts of the result (truncate very long output)
        rc = proc.returncode
        stdout_snip = proc.stdout[:2000] + ("...[truncated]" if len(proc.stdout) > 2000 else "")
        stderr_snip = proc.stderr[:2000] + ("...[truncated]" if len(proc.stderr) > 2000 else "")
        logger.info("Command finished: returncode=%s", rc)
        if stdout_snip:
            logger.info("stdout (snip): %s", stdout_snip.replace('\n', '\\n'))
        if stderr_snip:
            logger.info("stderr (snip): %s", stderr_snip.replace('\n', '\\n'))

        # Truncate output in returned dict to prevent LLM token overflow
        return {
            "ok": True,
            "cmd": cmd,
            "cwd": cwd,
            "returncode": rc,
            "stdout": _truncate_output(proc.stdout, MAX_STDOUT_CHARS, "stdout"),
            "stderr": _truncate_output(proc.stderr, MAX_STDERR_CHARS, "stderr"),
        }
    except subprocess.TimeoutExpired as te:
        logger.error("Command timeout: %r (timeout=%s)", cmd, timeout)
        return {"ok": False, "error": "timeout", "cmd": cmd, "cwd": cwd}
    except Exception as e:
        logger.exception("Unexpected error running command: %r", cmd)
        return {"ok": False, "error": str(e), "cmd": cmd, "cwd": cwd}


@mcp.tool()
def ripgrep_search(
    pattern: str,
    path: str = ".",
    glob: List[str] | None = None,
    max_results: int = 30,  # Reduced from 200 to prevent token overflow
) -> List[Dict[str, Any]]:
    """
    Search using ripgrep with safe, fixed flags:
    rg --hidden --no-ignore-vcs -n <pattern> <path>

    Returns structured matches:
    { path, line_no, line }
    This version logs the constructed command and each important step.
    """
    logger.info("ripgrep_search called: pattern=%r, path=%r, glob=%r, max_results=%s", pattern, path, glob, max_results)

    cmd = [
        "rg",
        "--hidden",
        "--no-ignore-vcs",
        "-n",
        pattern,
        path,
    ]

    # optional file globs: --glob '*.py'
    if glob:
        for g in glob:
            cmd.extend(["--glob", g])
    logger.info("Constructed ripgrep command: %s", cmd)

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        logger.error("ripgrep (rg) not installed or not found in PATH")
        return [{"error": "ripgrep (rg) not installed"}]
    except Exception as e:
        logger.exception("Error invoking ripgrep: %s", e)
        return [{"error": str(e)}]

    logger.info("ripgrep returncode=%s", proc.returncode)

    results = []
    if proc.returncode not in (0, 1):
        logger.error("ripgrep exited with unexpected return code %s: %s", proc.returncode, proc.stderr)
        return [{"error": proc.stderr.strip()}]

    output_lines = proc.stdout.splitlines()
    logger.info("ripgrep produced %d stdout lines", len(output_lines))

    for i, line in enumerate(output_lines):
        # format: path:line:content
        try:
            p, ln, content = line.split(":", 2)
            results.append(
                {
                    "path": p,
                    "line_no": int(ln),
                    "line": content,
                }
            )
        except ValueError:
            logger.warning("Skipping malformed ripgrep line %s: %r", i + 1, line)
            continue

        if len(results) >= max_results:
            logger.info("Reached max_results (%s); stopping", max_results)
            break

    logger.info("ripgrep_search returning %d matches", len(results))
    return results


@mcp.tool()
def run_shell(cmd: str, cwd: str | None = None, timeout: int = 30) -> Dict[str, Any]:
    logger.info("run_shell wrapper called: cmd=%r, cwd=%r, timeout=%s", cmd, cwd, timeout)
    return _run_shell(cmd, cwd=cwd, timeout=timeout)


@mcp.tool()
def git_status(cwd: str | None = None) -> Dict[str, Any]:
    logger.info("git_status called: cwd=%r", cwd)
    res = _run_shell("git status --porcelain", cwd=cwd)
    if res.get("ok"):
        logger.info("git_status output length=%s chars", len(res.get("stdout", "")))
    else:
        logger.error("git_status failed: %s", res)
    return res


@mcp.tool()
def git_create_branch(branch: str, cwd: str | None = None) -> Dict[str, Any]:
    logger.info("git_create_branch called: branch=%r, cwd=%r", branch, cwd)
    cmd = f"git checkout -b {shlex.quote(branch)}"
    logger.info("Running: %s", cmd)
    res = _run_shell(cmd, cwd=cwd)
    if res.get("ok"):
        logger.info("Created branch %s (returncode=%s)", branch, res.get("returncode"))
    else:
        logger.error("Failed to create branch %s: %s", branch, res)
    return res


@mcp.tool()
def git_commit(message: str, cwd: str | None = None) -> Dict[str, Any]:
    logger.info("git_commit called: message=%r, cwd=%r", message, cwd)
    r1 = _run_shell("git add -A", cwd=cwd)
    logger.info("git add result: %s", {"ok": r1.get("ok"), "returncode": r1.get("returncode")})
    if not r1.get("ok"):
        logger.error("git add failed: %s", r1)
        return r1
    res = _run_shell(f"git commit -m {shlex.quote(message)}", cwd=cwd)
    if res.get("ok"):
        logger.info("git commit succeeded: returncode=%s", res.get("returncode"))
    else:
        logger.error("git commit failed: %s", res)
    return res


@mcp.tool()
def git_push(remote: str = "origin", branch: str = "HEAD", cwd: str | None = None) -> Dict[str, Any]:
    logger.info("git_push called: remote=%r, branch=%r, cwd=%r", remote, branch, cwd)
    cmd = f"git push {shlex.quote(remote)} {shlex.quote(branch)}"
    logger.info("Running: %s", cmd)
    res = _run_shell(cmd, cwd=cwd)
    if res.get("ok"):
        logger.info("git push succeeded: returncode=%s", res.get("returncode"))
    else:
        logger.error("git push failed: %s", res)
    return res


if __name__ == "__main__":    
    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=8007
    )
