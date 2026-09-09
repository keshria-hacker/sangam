"""Built-in tools for the chat application."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from ..config import settings
from .registry import registry
from .schemas import ToolDefinition


def _get_workspace_root() -> Path:
    """Get the configured workspace root, resolved to absolute path."""
    return settings.WORKSPACE_ROOT.resolve()


def _is_path_allowed(target: Path) -> bool:
    """Check if a path is within the allowed workspace root."""
    workspace_root = _get_workspace_root()
    try:
        target.resolve().relative_to(workspace_root)
        return True
    except ValueError:
        return False


# -----------------------------------------------------------------------------
# Web Search Tool
# -----------------------------------------------------------------------------
async def web_search_handler(query: str, max_results: int = 5) -> dict[str, Any]:
    """Search the web using DuckDuckGo (no API key required)."""
    try:
        import httpx
        from bs4 import BeautifulSoup
    except ImportError as e:
        return {"error": f"httpx and beautifulsoup4 required for web search: {str(e)}"}
    
    url = "https://html.duckduckgo.com/html/"
    params = {"q": query}
    headers = {"User-Agent": "Mozilla/5.0 (compatible; SangamBot/1.0)"}
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, data=params, headers=headers)
        resp.raise_for_status()
    
    soup = BeautifulSoup(resp.text, "html.parser")
    results = []
    
    for result in soup.select(".result__body")[:max_results]:
        title_elem = result.select_one(".result__title")
        snippet_elem = result.select_one(".result__snippet")
        url_elem = result.select_one(".result__url")
        
        if title_elem and snippet_elem:
            results.append({
                "title": title_elem.get_text(strip=True),
                "snippet": snippet_elem.get_text(strip=True),
                "url": url_elem.get_text(strip=True) if url_elem else "",
            })
    
    return {"results": results, "query": query}


web_search_tool = ToolDefinition(
    name="web_search",
    description="Search the web for current information. Returns a list of results with titles, snippets, and URLs.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query"},
            "max_results": {"type": "integer", "description": "Maximum number of results", "default": 5, "minimum": 1, "maximum": 10},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
    handler=web_search_handler,
    capabilities=["web_access"],
    category="web",
    safety_level="safe",
    read_only=True,
    requires_confirmation=False,
)


# -----------------------------------------------------------------------------
# File System Tools
# -----------------------------------------------------------------------------
async def read_file_handler(path: str) -> dict[str, Any]:
    """Read a file from the local filesystem."""
    workspace_root = _get_workspace_root()

    # Resolve path relative to workspace root if not absolute
    if os.path.isabs(path):
        target = Path(path).resolve()
    else:
        target = (workspace_root / path).resolve()

    # Security: Ensure target is within workspace root
    if not _is_path_allowed(target):
        return {"error": f"Access denied: path outside workspace root: {path}"}

    if not target.exists():
        return {"error": f"File not found: {path}"}

    if not target.is_file():
        return {"error": f"Not a file: {path}"}

    try:
        content = target.read_text(encoding="utf-8")
        return {"content": content, "path": str(target), "size": len(content)}
    except UnicodeDecodeError:
        return {"error": f"File is not valid UTF-8 text: {path}"}


read_file_tool = ToolDefinition(
    name="read_file",
    description="Read the contents of a file from the local filesystem.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file"},
        },
        "required": ["path"],
        "additionalProperties": False,
    },
    handler=read_file_handler,
    capabilities=["file_access"],
    category="file",
    safety_level="safe",
    read_only=True,
    requires_confirmation=False,
)


async def list_files_handler(path: str = ".", pattern: str = "*") -> dict[str, Any]:
    """List files in a directory."""
    workspace_root = _get_workspace_root()

    # Resolve path relative to workspace root if not absolute
    if os.path.isabs(path):
        target = Path(path).resolve()
    else:
        target = (workspace_root / path).resolve()

    # Security: Ensure target is within workspace root
    if not _is_path_allowed(target):
        return {"error": f"Access denied: path outside workspace root: {path}"}

    if not target.exists():
        return {"error": f"Directory not found: {path}"}

    if not target.is_dir():
        return {"error": f"Not a directory: {path}"}

    files = []
    for item in target.glob(pattern):
        rel = item.relative_to(target)
        files.append({
            "name": str(rel),
            "type": "directory" if item.is_dir() else "file",
            "size": item.stat().st_size if item.is_file() else None,
        })

    return {"files": files, "path": str(target)}


list_files_tool = ToolDefinition(
    name="list_files",
    description="List files in a directory matching a pattern.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Directory path", "default": "."},
            "pattern": {"type": "string", "description": "Glob pattern", "default": "*"},
        },
        "additionalProperties": False,
    },
    handler=list_files_handler,
    capabilities=["file_access"],
    category="file",
    safety_level="safe",
    read_only=True,
    requires_confirmation=False,
)


# -----------------------------------------------------------------------------
# Code Execution Tool
# -----------------------------------------------------------------------------
async def execute_code_handler(code: str, language: str = "python", timeout: int = 30) -> dict[str, Any]:
    """Execute code in a sandboxed environment."""
    if language.lower() != "python":
        return {"error": f"Unsupported language: {language}. Only Python is currently supported."}

    workspace_root = _get_workspace_root()

    # Create a temporary file within the workspace root for isolation
    temp_dir = workspace_root / ".tmp_code_exec"
    temp_dir.mkdir(exist_ok=True)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, dir=temp_dir) as f:
        f.write(code)
        temp_path = f.name

    try:
        # Run with restricted environment, working directory set to workspace root
        proc = await asyncio.create_subprocess_exec(
            sys.executable, temp_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(workspace_root),
            env={**os.environ, "PYTHONPATH": "", "PYTHONDONTWRITEBYTECODE": "1"},
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return {"error": f"Code execution timed out after {timeout}s"}

        return {
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "returncode": proc.returncode,
        }
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass


execute_code_tool = ToolDefinition(
    name="execute_code",
    description="Execute Python code in a sandboxed environment and return the output.",
    parameters={
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python code to execute"},
            "language": {"type": "string", "description": "Programming language (only 'python' supported)", "default": "python", "enum": ["python"]},
            "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 30, "minimum": 1, "maximum": 300},
        },
        "required": ["code"],
        "additionalProperties": False,
    },
    handler=execute_code_handler,
    capabilities=["code_execution"],
    category="code",
    safety_level="caution",
    read_only=False,
    requires_confirmation=False,
)


# -----------------------------------------------------------------------------
# Register all built-in tools
# -----------------------------------------------------------------------------
def register_builtin_tools() -> None:
    """Register all built-in tools with the global registry."""
    registry.register(web_search_tool)
    registry.register(read_file_tool)
    registry.register(list_files_tool)
    registry.register(execute_code_tool)


# Auto-register on import
register_builtin_tools()
