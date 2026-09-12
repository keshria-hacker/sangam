import hashlib
import os
import shutil
import signal
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────────────
# Early check for Windows AppLocker / Application Control blocking pandas DLLs
# This gives a clear message instead of a cryptic traceback
# ──────────────────────────────────────────────────────────────────────────────
try:
    import pandas  # noqa: F401
except ImportError:
    # Not installed yet - will be handled by pip install
    pass
except OSError as e:
    if "Application Control policy" in str(e) or "blocked this file" in str(e):
        border = "=" * 70
        print(f"\n{border}", file=sys.stderr)
        print("  BLOCKED: Windows AppLocker / Application Control Policy", file=sys.stderr)
        print(f"  {e}", file=sys.stderr)
        print(border, file=sys.stderr)
        print("  This folder path is restricted by your organization's security policy.", file=sys.stderr)
        print("  The code is fine — the OS is preventing pandas DLLs from loading here.", file=sys.stderr)
        print("", file=sys.stderr)
        print("  SOLUTION: Clone/run from a NON-RESTRICTED path:", file=sys.stderr)
        print("    git clone https://github.com/keshria-hacker/sangam.git", file=sys.stderr)
        print("    cd sangam", file=sys.stderr)
        print("    python start.py", file=sys.stderr)
        print("", file=sys.stderr)
        print("  Or ask IT to whitelist this path in AppLocker.", file=sys.stderr)
        print(f"{border}\n", file=sys.stderr)
        sys.exit(1)
    # Re-raise other OSErrors
    raise

try:
    import psutil
except Exception:  # pragma: no cover - optional dependency
    psutil = None

# Ports the launcher binds. Listed here so a stale listener from a previous
# run (or a crashed instance) can be cleared before we start, instead of the
# backend failing with "[WinError 10048] only one usage of each socket
# address is normally permitted".
BACKEND_PORT = 8001
FRONTEND_PORT = 5500

ROOT = Path(__file__).resolve().parent
BACKEND_DIR = ROOT / "mainfiles" / "backend"
FRONTEND_DIR = ROOT / "mainfiles" / "frontend"
VENV_DIR = ROOT / "venv"
REQ_FILE = ROOT / "requirements.txt"
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"
REQUIREMENTS_MARKER = VENV_DIR / ".requirements.sha256"


# ── helpers ──────────────────────────────────────────────────────────────

def _print_error(msg: str, detail: str = "") -> None:
    """Print a clearly visible error banner."""
    border = "=" * 60
    print(f"\n{chr(27)}[91m{border}", file=sys.stderr)
    print(f"  ERROR: {msg}", file=sys.stderr)
    if detail:
        for line in detail.strip().splitlines():
            print(f"  | {line}", file=sys.stderr)
    print(f"{border}{chr(27)}[0m\n", file=sys.stderr)


def get_python_executable() -> str:
    if os.name == "nt":
        return str(VENV_DIR / "Scripts" / "python.exe")
    return str(VENV_DIR / "bin" / "python")


def free_port(port: int) -> None:
    """Terminate any process currently holding *port* so the launcher can bind.

    Uses ``psutil`` when available (cross-platform). On Windows without psutil
    we fall back to ``netstat`` + ``taskkill``. Failures are non-fatal — if we
    can't free the port the bind error will still surface, just as before.
    """
    pids: set[int] = set()
    if psutil is not None:
        for conn in psutil.net_connections(kind="tcp"):
            if getattr(conn, "laddr", None) and getattr(conn.laddr, "port", None) == port:
                if conn.pid:
                    pids.add(conn.pid)
    elif os.name == "nt":
        # netstat -ano: last column is the PID.
        out = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True, text=True,
        ).stdout
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[1].endswith(f":{port}") and parts[3] == "LISTENING":
                try:
                    pids.add(int(parts[4]))
                except ValueError:
                    pass

    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception:
            continue
    if pids:
        time.sleep(1)


def ensure_virtualenv() -> str:
    if not VENV_DIR.exists():
        subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True, cwd=ROOT)
    return get_python_executable()


def install_requirements(python_exe: str) -> None:
    fingerprint = hashlib.sha256(REQ_FILE.read_bytes()).hexdigest()
    if REQUIREMENTS_MARKER.exists() and REQUIREMENTS_MARKER.read_text(encoding="utf-8") == fingerprint:
        return
    subprocess.run([python_exe, "-m", "pip", "install", "--upgrade", "pip"], check=True, cwd=ROOT)
    subprocess.run([python_exe, "-m", "pip", "install", "-r", str(REQ_FILE)], check=True, cwd=ROOT)
    REQUIREMENTS_MARKER.write_text(fingerprint, encoding="utf-8")


def ensure_env_file() -> None:
    if not ENV_FILE.exists() and ENV_EXAMPLE.exists():
        shutil.copy2(ENV_EXAMPLE, ENV_FILE)
        print(f"Created {ENV_FILE.name} from {ENV_EXAMPLE.name} - edit it to add your API keys.")

    if not ENV_FILE.exists():
        return

    # Ensure MASTER_KEY has an actual value (not just a present-but-empty line —
    # `.env.example` ships `MASTER_KEY=` on purpose so it's obvious in the file,
    # but an empty value still leaves provider-key encryption broken).
    if "MASTER_KEY" in os.environ and os.environ["MASTER_KEY"].strip():
        return

    lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    has_real_value = any(
        line.strip().startswith("MASTER_KEY=")
        and not line.strip().startswith("#")
        and line.split("=", 1)[1].strip()
        for line in lines
    )
    if has_real_value:
        return

    # Generate a fresh Fernet key and write it into .env automatically so a
    # first-time run works without any manual setup step.
    from cryptography.fernet import Fernet
    new_key = Fernet.generate_key().decode()

    if any(line.strip().startswith("MASTER_KEY=") for line in lines):
        lines = [
            f"MASTER_KEY={new_key}" if line.strip().startswith("MASTER_KEY=") else line
            for line in lines
        ]
    else:
        lines.append(f"MASTER_KEY={new_key}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("Generated a new MASTER_KEY in .env (used to encrypt provider API keys at rest).")

def build_commands(python_exe: str):
    backend_cmd = [python_exe, "-m", "uvicorn", "mainfiles.backend.main:app", "--host", "127.0.0.1", "--port", str(BACKEND_PORT)]
    frontend_cmd = [python_exe, "-m", "http.server", str(FRONTEND_PORT)]
    return backend_cmd, frontend_cmd


def main() -> None:
    python_exe = ensure_virtualenv()
    install_requirements(python_exe)
    ensure_env_file()

    # Clear any stale listeners from previous/crashed runs before binding.
    free_port(BACKEND_PORT)
    free_port(FRONTEND_PORT)

    backend_cmd, frontend_cmd = build_commands(python_exe)

    print("=== sangam — starting ===")
    print(f"-> Backend: http://127.0.0.1:{BACKEND_PORT}/docs")
    print(f"-> Frontend: http://127.0.0.1:{FRONTEND_PORT}")
    print("-> Provider keys can be added from Settings -> Provider API Keys")

    # Start frontend FIRST to avoid inheriting backend's stdout pipe handle on Windows.
    # If backend starts first with stdout=PIPE, the frontend inherits the pipe and
    # http.server closes connections prematurely.
    frontend_proc = subprocess.Popen(frontend_cmd, cwd=FRONTEND_DIR)
    # Small delay to ensure frontend process is fully initialized before
    # backend creates its stdout pipe (which would be inherited otherwise).
    time.sleep(0.5)
    backend_proc = subprocess.Popen(
        backend_cmd, cwd=ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )

    # Thread to tee backend output to console in real time
    import threading
    def _tee_backend_output():
        try:
            for line in backend_proc.stdout or []:
                print(line, end="", flush=True)
        except Exception:
            pass
    tee_thread = threading.Thread(target=_tee_backend_output, daemon=True)
    tee_thread.start()

    # Wait for BOTH servers to be listening before auto-opening the browser.
    try:
        import socket, urllib.request

        def _port_open(port: int, timeout: float = 1.0) -> bool:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(timeout)
                return s.connect_ex(("127.0.0.1", port)) == 0

        def _backend_ready(timeout: float = 2.0) -> bool:
            try:
                r = urllib.request.urlopen(
                    f"http://127.0.0.1:{BACKEND_PORT}/api/auth/status",
                    timeout=timeout,
                )
                return r.status == 200
            except Exception:
                return False

        # Phase 1 — wait for TCP sockets to accept (up to ~3 s)
        for _ in range(30):
            frontend_up = _port_open(FRONTEND_PORT)
            backend_up = _port_open(BACKEND_PORT)
            if frontend_up and backend_up:
                break
            time.sleep(0.1)

        # Phase 2 — wait for backend HTTP to be healthy (up to ~5 s more)
        # so the browser never sees a loading spinner on first paint.
        backend_healthy = False
        for _ in range(25):
            if _backend_ready():
                backend_healthy = True
                break
            # If the backend process has already exited, don't keep waiting
            if backend_proc.poll() is not None:
                break
            time.sleep(0.2)

        if not backend_healthy:
            _print_error(
                "Backend failed to start or crashed.",
                (
                    "Check the output above for the exact error.\n"
                    "Common causes:\n"
                    "  • Port 8001 is already in use — close the other application\n"
                    "  • Missing dependencies — run: pip install -r requirements.txt\n"
                    "  • Invalid .env file — check MASTER_KEY and other settings\n"
                    "\n"
                    "After fixing, run this script again."
                ),
            )

        if _port_open(FRONTEND_PORT) and backend_healthy:
            webbrowser.open(f"http://127.0.0.1:{FRONTEND_PORT}")
    except BaseException as exc:
        _print_error(f"Startup interrupted or failed: {exc}")
        for proc in (backend_proc, frontend_proc):
            if proc.poll() is None:
                proc.terminate()
        raise

    def stop_all(signum, _frame):
        for proc in (backend_proc, frontend_proc):
            if proc.poll() is None:
                proc.terminate()
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, stop_all)
    signal.signal(signal.SIGTERM, stop_all)

    try:
        while True:
            if backend_proc.poll() is not None or frontend_proc.poll() is not None:
                break
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping servers...")
    finally:
        for proc in (backend_proc, frontend_proc):
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()


if __name__ == "__main__":
    main()
