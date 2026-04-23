from __future__ import annotations

import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

APP_DIR_NAME = "DeepWorkTimer"
MAX_WORK_MINUTES = 24 * 60
MAX_REST_MINUTES = 24 * 60
MAX_ROUNDS = 100


@dataclass
class TimerConfig:
    work_minutes: int
    rest_minutes: int
    rounds: int


DEFAULT_CONFIG = TimerConfig(work_minutes=90, rest_minutes=15, rounds=4)


@dataclass
class SessionStats:
    daily_sessions: int
    total_sessions: int
    daily_minutes: int
    weekly_average_minutes: float
    total_minutes: int
    sessions_per_day_last_week: float
    average_minutes_per_day_last_week: float


def _app_data_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    return Path.home() / ".local" / "share" / APP_DIR_NAME


DB_PATH = _app_data_dir() / "timer.db"


def _validate_config(config: TimerConfig) -> None:
    if not 1 <= config.work_minutes <= MAX_WORK_MINUTES:
        raise ValueError("work_minutes must be within the supported range")
    if not 0 <= config.rest_minutes <= MAX_REST_MINUTES:
        raise ValueError("rest_minutes must be within the supported range")
    if not 1 <= config.rounds <= MAX_ROUNDS:
        raise ValueError("rounds must be within the supported range")


class SessionStore:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(db_path)
        self.connection.row_factory = sqlite3.Row
        self._initialize()

    def _initialize(self) -> None:
        with self.connection:
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    completed_at TEXT NOT NULL,
                    work_minutes INTEGER NOT NULL
                )
                """
            )
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )

    def _coerce_setting(
        self, values: dict[str, str], key: str, default: int, minimum: int, maximum: int
    ) -> int:
        raw_value = values.get(key)
        try:
            value = int(raw_value) if raw_value is not None else default
        except ValueError:
            return default

        if minimum <= value <= maximum:
            return value
        return default

    def get_saved_config(self) -> TimerConfig:
        rows = self.connection.execute("SELECT key, value FROM settings").fetchall()
        values = {row["key"]: row["value"] for row in rows}
        return TimerConfig(
            work_minutes=self._coerce_setting(
                values,
                "work_minutes",
                DEFAULT_CONFIG.work_minutes,
                1,
                MAX_WORK_MINUTES,
            ),
            rest_minutes=self._coerce_setting(
                values,
                "rest_minutes",
                DEFAULT_CONFIG.rest_minutes,
                0,
                MAX_REST_MINUTES,
            ),
            rounds=self._coerce_setting(
                values,
                "rounds",
                DEFAULT_CONFIG.rounds,
                1,
                MAX_ROUNDS,
            ),
        )

    def save_config(self, config: TimerConfig) -> None:
        _validate_config(config)
        items = {
            "work_minutes": str(config.work_minutes),
            "rest_minutes": str(config.rest_minutes),
            "rounds": str(config.rounds),
        }
        with self.connection:
            self.connection.executemany(
                "INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)",
                items.items(),
            )

    def record_work_session(self, work_minutes: int) -> None:
        if not 1 <= work_minutes <= MAX_WORK_MINUTES:
            raise ValueError("work_minutes must be within the supported range")

        with self.connection:
            self.connection.execute(
                "INSERT INTO sessions(completed_at, work_minutes) VALUES (?, ?)",
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), work_minutes),
            )

    def get_stats(self) -> SessionStats:
        daily_row = self.connection.execute(
            """
            SELECT COUNT(*) AS count, COALESCE(SUM(work_minutes), 0) AS minutes
            FROM sessions
            WHERE DATE(completed_at) = DATE('now', 'localtime')
            """
        ).fetchone()
        total_row = self.connection.execute(
            """
            SELECT
                COUNT(*) AS count,
                COALESCE(SUM(work_minutes), 0) AS minutes,
                MIN(completed_at) AS first_completed_at
            FROM sessions
            """
        ).fetchone()
        last_week_row = self.connection.execute(
            """
            SELECT COUNT(*) AS count, COALESCE(SUM(work_minutes), 0) AS minutes
            FROM sessions
            WHERE DATE(completed_at) BETWEEN DATE('now', 'localtime', '-6 days')
                AND DATE('now', 'localtime')
            """
        ).fetchone()

        daily_sessions = daily_row["count"]
        total_sessions = total_row["count"]
        daily_minutes = int(daily_row["minutes"])
        total_minutes = int(total_row["minutes"])

        weekly_average_minutes = 0.0
        first_completed_at = total_row["first_completed_at"]
        if first_completed_at:
            first_date = datetime.strptime(first_completed_at, "%Y-%m-%d %H:%M:%S").date()
            weeks_tracked = max(1, ((datetime.now().date() - first_date).days // 7) + 1)
            weekly_average_minutes = total_minutes / weeks_tracked

        sessions_per_day_last_week = last_week_row["count"] / 7
        average_minutes_per_day_last_week = last_week_row["minutes"] / 7

        return SessionStats(
            daily_sessions=daily_sessions,
            total_sessions=total_sessions,
            daily_minutes=daily_minutes,
            weekly_average_minutes=weekly_average_minutes,
            total_minutes=total_minutes,
            sessions_per_day_last_week=sessions_per_day_last_week,
            average_minutes_per_day_last_week=average_minutes_per_day_last_week,
        )

    def close(self) -> None:
        self.connection.close()
