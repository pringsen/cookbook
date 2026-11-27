"""Runtime configuration, read from environment variables."""
import os
import secrets
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
UPLOAD_DIR = DATA_DIR / "uploads"

# Default to a local SQLite file so the app also runs without Postgres (dev / tiny installs).
DATABASE_URL = os.environ.get("DATABASE_URL") or f"sqlite:///{DATA_DIR / 'cookbook.db'}"

# Optional: AI settings can also be set in the web UI (Settings page). Env wins if set.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
AI_MODEL = os.environ.get("AI_MODEL", "").strip()
DEFAULT_AI_MODEL = "claude-opus-5-5"

# Set to "true" when the app is served over HTTPS (e.g. behind a reverse proxy) so cookies are Secure.
SECURE_COOKIES = os.environ.get("SECURE_COOKIES", "false").lower() == "true"

TIMEZONE = os.environ.get("TZ", "UTC")


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def secret_key() -> str:
    """SECRET_KEY from env, else a random key generated once and kept in the data folder."""
    env = os.environ.get("SECRET_KEY", "").strip()
    if env:
        return env
    ensure_dirs()
    path = DATA_DIR / ".secret_key"
    if path.exists():
        return path.read_text().strip()
    key = secrets.token_urlsafe(48)
    path.write_text(key)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return key
