"""Bounded, project-local monitoring history. Never stores provider payloads."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from promptdrift.errors import PromptDriftError
from promptdrift.models.monitor import MonitorReport

HISTORY_SCHEMA_VERSION = 1


def history_path(config_path: Path) -> Path:
    return config_path.parent / ".promptdrift" / "history.sqlite3"


def _validate_history_schema(db: sqlite3.Connection) -> int:
    version = db.execute("PRAGMA user_version").fetchone()[0]

    if version > HISTORY_SCHEMA_VERSION:
        raise PromptDriftError(
            "Monitoring history schema is newer than this PromptDrift version; "
            "back up or remove the local history database."
        )

    table = db.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'monitor_runs'"
    ).fetchone()

    if table is None:
        raise PromptDriftError(
            "Monitoring history schema is incompatible; "
            "back up or remove the local history database."
        )

    columns = [row[1] for row in db.execute("PRAGMA table_info(monitor_runs)").fetchall()]

    if columns != ["run_id", "report_json"]:
        raise PromptDriftError(
            "Monitoring history schema is incompatible; "
            "back up or remove the local history database."
        )

    return version


def _ensure_history_schema(db: sqlite3.Connection) -> None:
    version = db.execute("PRAGMA user_version").fetchone()[0]

    table = db.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'monitor_runs'"
    ).fetchone()

    if table is None:
        if version != 0:
            raise PromptDriftError(
                "Monitoring history schema is incompatible; "
                "back up or remove the local history database."
            )

        db.execute("CREATE TABLE monitor_runs (run_id TEXT PRIMARY KEY, report_json TEXT NOT NULL)")
        db.execute(f"PRAGMA user_version = {HISTORY_SCHEMA_VERSION}")
        return

    version = _validate_history_schema(db)

    if version == 0:
        db.execute(f"PRAGMA user_version = {HISTORY_SCHEMA_VERSION}")


def _history_write_error(exc: Exception) -> PromptDriftError:
    message = str(exc).lower()

    if isinstance(exc, sqlite3.OperationalError) and (
        "database is locked" in message or "database is busy" in message
    ):
        return PromptDriftError(
            "Monitoring history database is locked; "
            "close other PromptDrift processes using the history database and retry."
        )

    if isinstance(exc, sqlite3.DatabaseError) and (
        "file is not a database" in message
        or "database disk image is malformed" in message
        or "malformed" in message
    ):
        return PromptDriftError(
            "Monitoring history database appears corrupted; "
            "back up the database, then remove it and rerun monitoring."
        )

    return PromptDriftError("Monitoring completed but local history could not be saved.")


def save_monitor_report(report: MonitorReport, path: Path, *, retention: int = 1000) -> None:
    if retention < 1:
        raise ValueError("retention must be positive")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path, timeout=5)) as db, db:
            _ensure_history_schema(db)
            db.execute(
                "INSERT INTO monitor_runs VALUES (?, ?)", (report.run_id, report.model_dump_json())
            )
            db.execute(
                "DELETE FROM monitor_runs WHERE rowid NOT IN (SELECT rowid FROM monitor_runs ORDER BY rowid DESC LIMIT ?)",
                (retention,),
            )
    except (OSError, sqlite3.Error) as exc:
        raise _history_write_error(exc) from exc


def _history_read_error(exc: Exception) -> PromptDriftError:
    message = str(exc).lower()

    if isinstance(exc, sqlite3.OperationalError) and (
        "database is locked" in message or "database is busy" in message
    ):
        return PromptDriftError(
            "Monitoring history database is locked; "
            "close other PromptDrift processes using the history database and retry."
        )

    if isinstance(exc, sqlite3.DatabaseError) and (
        "file is not a database" in message
        or "database disk image is malformed" in message
        or "malformed" in message
    ):
        return PromptDriftError(
            "Monitoring history database appears corrupted; "
            "back up the database, then remove it and rerun monitoring."
        )

    return PromptDriftError(
        "Monitoring history is unreadable; back up or remove the local history database."
    )


def load_monitor_history(path: Path, *, limit: int = 20) -> list[dict]:
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    if not path.exists():
        return []
    try:
        with closing(
            sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
        ) as db:
            _validate_history_schema(db)
            rows = db.execute(
                "SELECT report_json FROM monitor_runs ORDER BY rowid DESC LIMIT ?", (limit,)
            ).fetchall()
        return [json.loads(row[0]) for row in rows]
    except (OSError, sqlite3.Error, ValueError) as exc:
        raise _history_read_error(exc) from exc


def load_monitor_run_by_id(path: Path, run_id: str) -> MonitorReport:
    """Retrieve a specific monitoring report by its run_id."""
    if not path.exists():
        raise PromptDriftError(f"Monitoring history database not found: {path}")
    try:
        with closing(
            sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
        ) as db:
            _validate_history_schema(db)
            row = db.execute(
                "SELECT report_json FROM monitor_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            raise PromptDriftError(f"Monitoring run '{run_id}' not found in history.")
        data = json.loads(row[0])
        if not isinstance(data, dict):
            raise PromptDriftError(
                f"Monitoring run '{run_id}' is corrupted; back up the database, "
                "then remove the run or the database."
            )
        data.pop("counts", None)
        data.pop("diagnosis_counts", None)
        return MonitorReport.model_validate(data)
    except (OSError, sqlite3.Error, ValueError) as exc:
        if isinstance(exc, PromptDriftError):
            raise
        raise _history_read_error(exc) from exc
