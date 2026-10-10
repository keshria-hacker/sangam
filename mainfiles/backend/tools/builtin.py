"""Built-in tools for the chat application."""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from ..config import settings
from ..feature_flags import is_enabled
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
        except TimeoutError:
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
# Image Generation Tool (image-gen theme)
# -----------------------------------------------------------------------------
async def generate_image_handler(
    prompt: str, style: str | None = None, size: str | None = None
) -> dict[str, Any]:
    """Generate an image from a text prompt via the configured engine."""
    from ..config import settings as _settings

    if not is_enabled("image_gen"):
        return {"error": "Image generation is not enabled (FEATURE_IMAGE_GEN=false)."}
    try:
        from ..image_gen import ImageGenError, generate_images

        attachments = generate_images(prompt, style=style, size=size, n=1)
    except Exception as exc:  # noqa: BLE001 — report, never raise
        return {"error": f"Image generation failed: {exc}"}
    if not attachments:
        return {"error": "The engine returned no images."}
    a = attachments[0]
    return {
        "image_url": a.url,
        "media_id": a.id,
        "mime_type": a.mime_type,
        # Hint for the model: embed this markdown so the image renders in chat.
        "markdown": f"![generated image]({a.url})",
    }


generate_image_tool = ToolDefinition(
    name="generate_image",
    description=(
        "Generate an image from a text prompt. Returns the image URL, media id, "
        "and markdown to embed so the image renders in the chat. Use when the "
        "user asks for an image, illustration, or visual."
    ),
    parameters={
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "Detailed image description"},
            "style": {
                "type": "string",
                "description": "Style preset: photographic, cinematic, digital-art, anime, portrait, landscape, fantasy, none",
            },
            "size": {"type": "string", "description": "e.g. 1024x1024, 1792x1024"},
        },
        "required": ["prompt"],
        "additionalProperties": False,
    },
    handler=generate_image_handler,
    capabilities=["image_generation"],
    category="general",
    safety_level="safe",
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
    registry.register(generate_image_tool)
    registry.register(write_file_tool)
    registry.register(edit_file_tool)
    registry.register(run_bash_tool)
    registry.register(code_map_tool)




async def write_file_handler(path: str, content: str) -> dict[str, Any]:
    """Write (create or overwrite) a file in the workspace."""
    workspace_root = _get_workspace_root()
    if os.path.isabs(path):
        target = Path(path).resolve()
    else:
        target = (workspace_root / path).resolve()
    if not _is_path_allowed(target):
        return {"error": f"Access denied: path outside workspace root: {path}"}
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {"ok": True, "path": str(target), "size": len(content)}
    except OSError as exc:
        return {"error": f"Write failed: {exc}"}


write_file_tool = ToolDefinition(
    name="write_file",
    description="Create or overwrite a file with the given content. Creates parent directories as needed.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file"},
            "content": {"type": "string", "description": "Full file content"},
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    },
    handler=write_file_handler,
    capabilities=["file_access", "file_write"],
    category="file",
    safety_level="caution",
    read_only=False,
    requires_confirmation=False,
)


async def edit_file_handler(path: str, old_text: str, new_text: str) -> dict[str, Any]:
    """Replace old_text with new_text in a file (exact match required)."""
    workspace_root = _get_workspace_root()
    if os.path.isabs(path):
        target = Path(path).resolve()
    else:
        target = (workspace_root / path).resolve()
    if not _is_path_allowed(target):
        return {"error": f"Access denied: path outside workspace root: {path}"}
    if not target.is_file():
        return {"error": f"File not found: {path}"}
    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return {"error": f"File is not valid UTF-8 text: {path}"}
    if old_text not in content:
        return {"error": "old_text not found in file (exact match required)"}
    count = content.count(old_text)
    content = content.replace(old_text, new_text, 1)
    target.write_text(content, encoding="utf-8")
    return {"ok": True, "path": str(target), "replacements": 1, "other_matches": count - 1}


edit_file_tool = ToolDefinition(
    name="edit_file",
    description="Replace an exact text snippet in a file. Fails if old_text is not found verbatim.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file"},
            "old_text": {"type": "string", "description": "Exact text to replace"},
            "new_text": {"type": "string", "description": "Replacement text"},
        },
        "required": ["path", "old_text", "new_text"],
        "additionalProperties": False,
    },
    handler=edit_file_handler,
    capabilities=["file_access", "file_write"],
    category="file",
    safety_level="caution",
    read_only=False,
    requires_confirmation=False,
)


async def run_bash_handler(command: str, timeout: int = 60) -> dict[str, Any]:
    """Run a bash command in the workspace sandbox. Returns stdout/stderr."""
    import asyncio as _asyncio
    workspace_root = _get_workspace_root()
    try:
        proc = await _asyncio.create_subprocess_shell(
            command,
            stdout=_asyncio.subprocess.PIPE,
            stderr=_asyncio.subprocess.PIPE,
            cwd=str(workspace_root),
        )
        try:
            out, err = await _asyncio.wait_for(proc.communicate(), timeout=timeout)
        except _asyncio.TimeoutError:
            proc.kill()
            return {"error": f"Command timed out after {timeout}s", "command": command}
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": out.decode("utf-8", "replace")[:20000],
            "stderr": err.decode("utf-8", "replace")[:20000],
            "command": command,
        }
    except Exception as exc:
        return {"error": f"Bash failed: {exc}", "command": command}


run_bash_tool = ToolDefinition(
    name="run_bash",
    description="Execute a bash command in the workspace directory. Returns stdout, stderr, and exit code.",
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Bash command to run"},
            "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 60},
        },
        "required": ["command"],
        "additionalProperties": False,
    },
    handler=run_bash_handler,
    capabilities=["code_execution", "terminal"],
    category="code",
    safety_level="caution",
    read_only=False,
    requires_confirmation=False,
)



_code_graph_cache: dict | None = None


async def code_map_handler(query: str, target: str = "") -> dict[str, Any]:
    """Query the AST code map: explain a symbol or trace a path between two symbols."""
    global _code_graph_cache
    from ..code_graph import build_graph, explain, find_path
    if _code_graph_cache is None:
        _code_graph_cache = build_graph()
    if query == "explain":
        return explain(target, _code_graph_cache)
    if query == "path" and "->" in target:
        a, b = [s.strip() for s in target.split("->", 1)]
        return find_path(a, b, _code_graph_cache)
    return {"error": "query must be 'explain' or 'path'; for path use target='A -> B'"}


code_map_tool = ToolDefinition(
    name="code_map",
    description="Query the codebase map (AST-based, no LLM cost). query='explain', target='symbol_name' shows what calls it. query='path', target='A -> B' traces how A connects to B.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "enum": ["explain", "path"]},
            "target": {"type": "string", "description": "Symbol name, or 'A -> B' for path"},
        },
        "required": ["query", "target"],
        "additionalProperties": False,
    },
    handler=code_map_handler,
    capabilities=["code_analysis"],
    category="code",
    safety_level="safe",
    read_only=True,
    requires_confirmation=False,
)


# Auto-register on import
register_builtin_tools()