"""
Structured JSON logging for the ingestion pipeline.

Each call emits one JSON line to stdout. Cloud Run / Cloud Logging automatically
parses the `severity` field for log level routing.
"""
import json
import sys


def log(severity: str, message: str, **fields) -> None:
    """Emit one structured JSON log line to stdout."""
    entry = {"severity": severity, "message": message, **fields}
    print(json.dumps(entry, ensure_ascii=False), flush=True)


def info(message: str, **fields) -> None:
    log("INFO", message, **fields)


def warning(message: str, **fields) -> None:
    log("WARNING", message, **fields)


def error(message: str, **fields) -> None:
    entry = {"severity": "ERROR", "message": message, **fields}
    print(json.dumps(entry, ensure_ascii=False), flush=True, file=sys.stderr)
