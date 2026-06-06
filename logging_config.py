"""Lightweight logging: rotating file (10MB × 3) + console, unified format.

app + uvicorn loggers share the same format, auto-rotated, no log loss.
"""

import logging
import logging.handlers
import os
from pathlib import Path

_DEFAULT_LOG_DIR = str(Path(__file__).resolve().parent.parent / "logs")
_DEFAULT_LEVEL = "INFO"
_LOG_FMT = "%(asctime)s [%(levelname)-5s] %(name)s: %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"


def configure_logging(log_dir: str = "", level: str = "") -> str:
    """Set up logging: rotating file + console, inherited by uvicorn child loggers.

    Env overrides:
      NOLLMKB_LOG_DIR  default ../logs (sibling to nollmkb)
      NOLLMKB_LOG_LEVEL default INFO

    Returns: log file path.
    """
    log_dir = log_dir or os.environ.get("NOLLMKB_LOG_DIR", _DEFAULT_LOG_DIR)
    level_name = level or os.environ.get("NOLLMKB_LOG_LEVEL", _DEFAULT_LEVEL)
    log_level = getattr(logging, level_name.upper(), logging.INFO)

    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "nollmkb.log")

    fmt = logging.Formatter(_LOG_FMT, _DATE_FMT)

    # --- file: 10 MB × 3 rotated ---
    fh = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8",
    )
    fh.setFormatter(fmt)
    fh.setLevel(log_level)

    # --- console: stderr ---
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    ch.setLevel(log_level)

    # --- root logger (uvicorn + all app loggers inherit) ---
    root = logging.getLogger()
    root.setLevel(log_level)
    root.handlers.clear()
    root.addHandler(fh)
    root.addHandler(ch)

    # --- quiet noisy third-party loggers ---
    logging.getLogger("chromadb").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    return log_path
