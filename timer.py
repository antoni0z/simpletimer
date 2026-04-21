from __future__ import annotations

import sqlite3
import subprocess
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Optional


APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "timer.db"
MACOS_ALERT_SOUND = "/System/Library/Sounds/Glass.aiff"


@dataclass
class TimerConfig:
    work_minutes: int
    rest_minutes: int
    rounds: int


@dataclass
class SessionStats:
    daily_sessions: int
    total_sessions: int
    daily_minutes: int
    weekly_average_minutes: float
    total_minutes: int
    sessions_per_day_last_week: float
    average_minutes_per_day_last_week: float


class SessionStore:
    def __init__(self, db_path: Path) -> None:
        self.connection = sqlite3.connect(db_path)
        self.connection.row_factory = sqlite3.Row
        self._initialize()

    def _initialize(self) -> None:
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
        self.connection.commit()

    def get_saved_config(self) -> TimerConfig:
        rows = self.connection.execute("SELECT key, value FROM settings").fetchall()
        values = {row["key"]: row["value"] for row in rows}
        return TimerConfig(
            work_minutes=int(values.get("work_minutes", 50)),
            rest_minutes=int(values.get("rest_minutes", 10)),
            rounds=int(values.get("rounds", 4)),
        )

    def save_config(self, config: TimerConfig) -> None:
        items = {
            "work_minutes": str(config.work_minutes),
            "rest_minutes": str(config.rest_minutes),
            "rounds": str(config.rounds),
        }
        self.connection.executemany(
            "INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)",
            items.items(),
        )
        self.connection.commit()

    def record_work_session(self, work_minutes: int) -> None:
        self.connection.execute(
            "INSERT INTO sessions(completed_at, work_minutes) VALUES (?, ?)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), work_minutes),
        )
        self.connection.commit()

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


class DeepWorkTimerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.store = SessionStore(DB_PATH)
        self.saved_config = self.store.get_saved_config()

        self.timer_after_id: Optional[str] = None
        self.config: Optional[TimerConfig] = None
        self.is_running = False
        self.is_paused = False
        self.phase = "ready"
        self.current_round = 1
        self.remaining_seconds = self.saved_config.work_minutes * 60

        self.root.title("Deep Work Timer")
        self.root.geometry("860x760")
        self.root.minsize(780, 740)
        self.root.configure(bg="#ece7df")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.style = ttk.Style()
        self._configure_styles()
        self._build_ui()
        self._bind_input_updates()
        self._refresh_stats()
        self._update_timer_display()

    def _notify(self, title: str, message: str) -> None:
        escaped_title = title.replace("\\", "\\\\").replace('"', '\\"')
        escaped_message = message.replace("\\", "\\\\").replace('"', '\\"')
        notification_script = (
            f'display notification "{escaped_message}" with title "{escaped_title}" '
            'subtitle "Deep Work Timer"'
        )
        popup_script = (
            f'display dialog "{escaped_message}" with title "{escaped_title}" '
            'buttons {"OK"} default button "OK" giving up after 8'
        )

        try:
            subprocess.Popen(
                ["osascript", "-e", notification_script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            pass

        try:
            subprocess.Popen(
                ["osascript", "-e", popup_script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            pass

        self.root.bell()

        try:
            subprocess.Popen(
                ["afplay", MACOS_ALERT_SOUND],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            pass

    def _configure_styles(self) -> None:
        self.style.theme_use("clam")
        self.style.configure("App.TFrame", background="#ece7df")
        self.style.configure("Card.TFrame", background="#f4efe8")
        self.style.configure(
            "Title.TLabel",
            background="#ece7df",
            foreground="#28323a",
            font=("Helvetica", 28, "bold"),
        )
        self.style.configure(
            "Subtitle.TLabel",
            background="#ece7df",
            foreground="#6e7476",
            font=("Helvetica", 12),
        )
        self.style.configure(
            "Section.TLabel",
            background="#f4efe8",
            foreground="#2f3942",
            font=("Helvetica", 13, "bold"),
        )
        self.style.configure(
            "Body.TLabel",
            background="#f4efe8",
            foreground="#47535c",
            font=("Helvetica", 12),
        )
        self.style.configure(
            "Timer.TLabel",
            background="#f4efe8",
            foreground="#3b4851",
            font=("Menlo", 52, "bold"),
        )
        self.style.configure(
            "Value.TLabel",
            background="#f4efe8",
            foreground="#394650",
            font=("Helvetica", 26, "bold"),
        )
        self.style.configure(
            "Metric.TLabel",
            background="#f4efe8",
            foreground="#394650",
            font=("Helvetica", 20, "bold"),
        )
        self.style.configure(
            "MetricDetail.TLabel",
            background="#f4efe8",
            foreground="#6e7476",
            font=("Helvetica", 11),
        )
        self.style.configure(
            "Muted.TLabel",
            background="#f4efe8",
            foreground="#687074",
            font=("Helvetica", 11),
        )
        self.style.configure(
            "App.TButton",
            background="#6b7178",
            foreground="#ffffff",
            borderwidth=1,
            focusthickness=3,
            focuscolor="#6b7178",
            padding=(18, 10),
            font=("Helvetica", 11, "bold"),
        )
        self.style.map(
            "App.TButton",
            background=[("active", "#5f666d"), ("disabled", "#ddd9d1")],
            foreground=[("disabled", "#9a9d9b")],
        )
        self.style.configure(
            "Secondary.TButton",
            background="#efebe4",
            foreground="#4c5660",
            borderwidth=1,
            padding=(18, 10),
            font=("Helvetica", 11, "bold"),
        )
        self.style.map(
            "Secondary.TButton",
            background=[("active", "#e7e1d8"), ("disabled", "#ece8e1")],
            foreground=[("disabled", "#9a9d9b")],
        )
        self.style.configure(
            "App.TEntry",
            fieldbackground="#f6f2eb",
            foreground="#36424a",
            insertcolor="#36424a",
            bordercolor="#cbc3b8",
            lightcolor="#cbc3b8",
            darkcolor="#cbc3b8",
            padding=10,
        )

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        container = ttk.Frame(self.root, style="App.TFrame", padding=24)
        container.grid(sticky="nsew")
        container.columnconfigure(0, weight=3)
        container.columnconfigure(1, weight=2)
        container.rowconfigure(1, weight=1)

        header = ttk.Frame(container, style="App.TFrame")
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 18))
        ttk.Label(header, text="Deep Work Timer", style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )

        left_panel = ttk.Frame(container, style="App.TFrame")
        left_panel.grid(row=1, column=0, sticky="nsew", padx=(0, 16))
        left_panel.columnconfigure(0, weight=1)
        left_panel.rowconfigure(0, weight=4)
        left_panel.rowconfigure(1, weight=1)

        timer_card = ttk.Frame(left_panel, style="Card.TFrame", padding=24)
        timer_card.grid(row=0, column=0, sticky="nsew")
        timer_card.columnconfigure(0, weight=1)
        timer_card.rowconfigure(6, weight=1)

        ttk.Label(timer_card, text="Current Session", style="Section.TLabel").grid(
            row=0, column=0, sticky="w"
        )

        self.phase_label = ttk.Label(timer_card, text="Ready to focus", style="Body.TLabel")
        self.phase_label.grid(row=1, column=0, sticky="w", pady=(12, 0))

        self.round_label = ttk.Label(timer_card, text="Round 1 of 4", style="Muted.TLabel")
        self.round_label.grid(row=2, column=0, sticky="w", pady=(4, 12))

        self.timer_label = ttk.Label(timer_card, text="50:00", style="Timer.TLabel")
        self.timer_label.grid(row=3, column=0, sticky="w", pady=(8, 20))

        self.status_label = ttk.Label(
            timer_card,
            text="Set your block length, hit start, and the app will count finished work sessions for you.",
            style="Body.TLabel",
            wraplength=380,
            justify="left",
        )
        self.status_label.grid(row=4, column=0, sticky="w")

        controls = ttk.Frame(timer_card, style="Card.TFrame")
        controls.grid(row=5, column=0, sticky="ew", pady=(24, 0))
        controls.columnconfigure((0, 1, 2), weight=1)

        self.start_button = ttk.Button(
            controls,
            text="Start Session",
            style="App.TButton",
            command=self.start_session,
        )
        self.start_button.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self.pause_button = ttk.Button(
            controls,
            text="Pause",
            style="Secondary.TButton",
            command=self.toggle_pause,
            state="disabled",
        )
        self.pause_button.grid(row=0, column=1, sticky="ew", padx=8)

        self.reset_button = ttk.Button(
            controls,
            text="Reset",
            style="Secondary.TButton",
            command=self.reset_session,
            state="disabled",
        )
        self.reset_button.grid(row=0, column=2, sticky="ew", padx=(8, 0))

        snapshot_card = ttk.Frame(left_panel, style="Card.TFrame", padding=20)
        snapshot_card.grid(row=1, column=0, sticky="nsew", pady=(16, 0))
        snapshot_card.columnconfigure((0, 1), weight=1)

        ttk.Label(snapshot_card, text="Weekly Snapshot", style="Section.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        ttk.Label(snapshot_card, text="Sessions / Day", style="Muted.TLabel").grid(
            row=1, column=0, sticky="w", pady=(14, 4)
        )
        ttk.Label(snapshot_card, text="Avg Minutes / Day", style="Muted.TLabel").grid(
            row=1, column=1, sticky="w", pady=(14, 4)
        )

        self.weekly_sessions_per_day_label = ttk.Label(
            snapshot_card,
            text="0.0",
            style="Metric.TLabel",
        )
        self.weekly_sessions_per_day_label.grid(row=2, column=0, sticky="w")

        self.weekly_minutes_per_day_label = ttk.Label(
            snapshot_card,
            text="0m",
            style="Metric.TLabel",
        )
        self.weekly_minutes_per_day_label.grid(row=2, column=1, sticky="w")

        ttk.Label(
            snapshot_card,
            text="Based on the last 7 days.",
            style="MetricDetail.TLabel",
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(10, 0))

        side_panel = ttk.Frame(container, style="App.TFrame")
        side_panel.grid(row=1, column=1, sticky="nsew")
        side_panel.columnconfigure(0, weight=1)
        side_panel.rowconfigure(1, weight=1)

        settings_card = ttk.Frame(side_panel, style="Card.TFrame", padding=20)
        settings_card.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        settings_card.columnconfigure(0, weight=1)

        ttk.Label(settings_card, text="Session Settings", style="Section.TLabel").grid(
            row=0, column=0, sticky="w"
        )

        self.work_var = tk.StringVar(value=str(self.saved_config.work_minutes))
        self.rest_var = tk.StringVar(value=str(self.saved_config.rest_minutes))
        self.rounds_var = tk.StringVar(value=str(self.saved_config.rounds))

        self._build_labeled_entry(settings_card, 1, "Work minutes", self.work_var)
        self._build_labeled_entry(settings_card, 2, "Rest minutes", self.rest_var)
        self._build_labeled_entry(settings_card, 3, "Rounds", self.rounds_var)

        hint = (
            "A finished work block counts as one deep work session. "
            "Rest is skipped after the final round."
        )
        ttk.Label(settings_card, text=hint, style="Muted.TLabel", wraplength=240).grid(
            row=4, column=0, sticky="w", pady=(14, 0)
        )

        stats_card = ttk.Frame(side_panel, style="Card.TFrame", padding=20)
        stats_card.grid(row=1, column=0, sticky="nsew")
        stats_card.columnconfigure((0, 1, 2), weight=1)
        stats_card.rowconfigure(7, weight=1)

        ttk.Label(stats_card, text="Completed Sessions", style="Section.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="w"
        )

        ttk.Label(stats_card, text="Sessions", style="Body.TLabel").grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(16, 4)
        )
        ttk.Label(stats_card, text="Today", style="Muted.TLabel").grid(
            row=2, column=0, sticky="w", pady=(6, 4)
        )
        ttk.Label(stats_card, text="Total", style="Muted.TLabel").grid(
            row=2, column=1, sticky="w", pady=(6, 4)
        )

        self.daily_value_label = ttk.Label(stats_card, text="0", style="Value.TLabel")
        self.daily_value_label.grid(row=3, column=0, sticky="w")

        self.total_value_label = ttk.Label(stats_card, text="0", style="Value.TLabel")
        self.total_value_label.grid(row=3, column=1, sticky="w")

        ttk.Separator(stats_card, orient="horizontal").grid(
            row=4, column=0, columnspan=3, sticky="ew", pady=(18, 18)
        )

        ttk.Label(stats_card, text="Hours", style="Body.TLabel").grid(
            row=5, column=0, columnspan=3, sticky="w", pady=(0, 4)
        )
        ttk.Label(stats_card, text="Today", style="Muted.TLabel").grid(
            row=6, column=0, sticky="w", pady=(6, 4)
        )
        ttk.Label(stats_card, text="Weekly Avg", style="Muted.TLabel").grid(
            row=6, column=1, sticky="w", pady=(6, 4)
        )
        ttk.Label(stats_card, text="Total", style="Muted.TLabel").grid(
            row=6, column=2, sticky="w", pady=(6, 4)
        )

        self.daily_hours_value_label = ttk.Label(stats_card, text="0.0h", style="Metric.TLabel")
        self.daily_hours_value_label.grid(row=7, column=0, sticky="nw")
        self.daily_hours_detail_label = ttk.Label(
            stats_card,
            text="0m",
            style="MetricDetail.TLabel",
        )
        self.daily_hours_detail_label.grid(row=8, column=0, sticky="nw", pady=(6, 0))

        self.weekly_hours_value_label = ttk.Label(
            stats_card,
            text="0.0h",
            style="Metric.TLabel",
        )
        self.weekly_hours_value_label.grid(row=7, column=1, sticky="nw")
        self.weekly_hours_detail_label = ttk.Label(
            stats_card,
            text="0m / week",
            style="MetricDetail.TLabel",
        )
        self.weekly_hours_detail_label.grid(row=8, column=1, sticky="nw", pady=(6, 0))

        self.total_hours_value_label = ttk.Label(stats_card, text="0.0h", style="Metric.TLabel")
        self.total_hours_value_label.grid(row=7, column=2, sticky="nw")
        self.total_hours_detail_label = ttk.Label(
            stats_card,
            text="0m",
            style="MetricDetail.TLabel",
        )
        self.total_hours_detail_label.grid(row=8, column=2, sticky="nw", pady=(6, 0))

    def _build_labeled_entry(
        self, parent: ttk.Frame, row: int, label: str, variable: tk.StringVar
    ) -> None:
        frame = ttk.Frame(parent, style="Card.TFrame")
        frame.grid(row=row, column=0, sticky="ew", pady=(14, 0))
        frame.columnconfigure(0, weight=1)

        ttk.Label(frame, text=label, style="Body.TLabel").grid(row=0, column=0, sticky="w")
        entry = ttk.Entry(frame, textvariable=variable, style="App.TEntry", width=12)
        entry.grid(row=1, column=0, sticky="ew", pady=(6, 0))

    def _refresh_stats(self) -> None:
        stats = self.store.get_stats()
        self.daily_value_label.configure(text=str(stats.daily_sessions))
        self.total_value_label.configure(text=str(stats.total_sessions))
        self.daily_hours_value_label.configure(text=self._format_hours(stats.daily_minutes))
        self.daily_hours_detail_label.configure(text=self._format_duration(stats.daily_minutes))
        self.weekly_hours_value_label.configure(
            text=self._format_hours(stats.weekly_average_minutes)
        )
        self.weekly_hours_detail_label.configure(
            text=f"{self._format_duration(stats.weekly_average_minutes)} / week"
        )
        self.total_hours_value_label.configure(text=self._format_hours(stats.total_minutes))
        self.total_hours_detail_label.configure(text=self._format_duration(stats.total_minutes))
        self.weekly_sessions_per_day_label.configure(
            text=f"{stats.sessions_per_day_last_week:.1f}"
        )
        self.weekly_minutes_per_day_label.configure(
            text=f"{stats.average_minutes_per_day_last_week:.1f}m"
        )

    def _format_hours(self, minutes: float) -> str:
        hours = minutes / 60
        if hours <= 0:
            return "0.00h"

        if hours < 1:
            return f"{hours:.2f}h"

        return f"{hours:.1f}h"

    def _format_duration(self, minutes: float) -> str:
        rounded_minutes = int(round(minutes))
        if rounded_minutes <= 0:
            return "0m"

        hours, remainder = divmod(rounded_minutes, 60)
        if hours and remainder:
            return f"{hours}h {remainder}m"
        if hours:
            return f"{hours}h"
        return f"{remainder}m"

    def _bind_input_updates(self) -> None:
        for variable in (self.work_var, self.rest_var, self.rounds_var):
            variable.trace_add("write", self._handle_input_change)

    def _handle_input_change(self, *_args: object) -> None:
        if self.phase != "ready":
            return

        try:
            work_minutes = int(self.work_var.get())
        except ValueError:
            work_minutes = self.saved_config.work_minutes

        if work_minutes > 0:
            self.remaining_seconds = work_minutes * 60

        self._update_timer_display()

    def _get_config_from_inputs(self, show_errors: bool = True) -> Optional[TimerConfig]:
        try:
            work_minutes = int(self.work_var.get())
            rest_minutes = int(self.rest_var.get())
            rounds = int(self.rounds_var.get())
        except ValueError:
            if show_errors:
                messagebox.showerror("Invalid settings", "Use whole numbers for all fields.")
            return None

        if work_minutes <= 0:
            if show_errors:
                messagebox.showerror("Invalid settings", "Work minutes must be greater than 0.")
            return None
        if rest_minutes < 0:
            if show_errors:
                messagebox.showerror("Invalid settings", "Rest minutes cannot be negative.")
            return None
        if rounds <= 0:
            if show_errors:
                messagebox.showerror("Invalid settings", "Rounds must be greater than 0.")
            return None

        return TimerConfig(
            work_minutes=work_minutes,
            rest_minutes=rest_minutes,
            rounds=rounds,
        )

    def start_session(self) -> None:
        if self.is_running:
            return

        if self.phase in {"ready", "complete"}:
            config = self._get_config_from_inputs()
            if config is None:
                return
            self.config = config
            self.saved_config = config
            self.store.save_config(config)
            self.current_round = 1
            self.phase = "work"
            self.remaining_seconds = config.work_minutes * 60
            self._set_inputs_state("disabled")
        elif self.config is None:
            return

        self.is_running = True
        self.is_paused = False
        self.pause_button.configure(text="Pause", state="normal")
        self.reset_button.configure(state="normal")
        self.start_button.configure(text="Start Session", state="disabled")
        self._update_status_text()
        self._update_timer_display()
        self._schedule_tick()

    def toggle_pause(self) -> None:
        if self.phase in {"ready", "complete"} or self.config is None:
            return

        if self.is_running:
            self.is_running = False
            self.is_paused = True
            self._cancel_scheduled_tick()
            self.pause_button.configure(text="Resume")
            self.start_button.configure(text="Resume", state="normal")
            self.phase_label.configure(text=f"{self._phase_title()} paused")
            self.status_label.configure(text="Timer paused. Resume when you want to continue the block.")
        elif self.is_paused:
            self.start_button.configure(text="Start Session", state="disabled")
            self.start_session()

    def reset_session(self) -> None:
        self._cancel_scheduled_tick()

        self.is_running = False
        self.is_paused = False
        self.phase = "ready"
        self.config = None
        self.current_round = 1

        config = self._get_config_from_inputs(show_errors=False) or self.saved_config
        self.remaining_seconds = config.work_minutes * 60
        self._set_inputs_state("normal")
        self.start_button.configure(text="Start Session", state="normal")
        self.pause_button.configure(text="Pause", state="disabled")
        self.reset_button.configure(state="disabled")
        self.phase_label.configure(text="Ready to focus")
        self.round_label.configure(text=f"Round 1 of {config.rounds}")
        self.status_label.configure(
            text="Set your block length, hit start, and the app will count finished work sessions for you."
        )
        self._update_timer_display()

    def _cancel_scheduled_tick(self) -> None:
        if self.timer_after_id is None:
            return

        try:
            self.root.after_cancel(self.timer_after_id)
        except tk.TclError:
            pass
        finally:
            self.timer_after_id = None

    def _set_inputs_state(self, state: str) -> None:
        for child in self.root.winfo_children():
            self._set_entry_state_recursive(child, state)

    def _set_entry_state_recursive(self, widget: tk.Misc, state: str) -> None:
        if isinstance(widget, ttk.Entry):
            widget.configure(state=state)
        for child in widget.winfo_children():
            self._set_entry_state_recursive(child, state)

    def _schedule_tick(self) -> None:
        if self.is_running:
            self.timer_after_id = self.root.after(1000, self._tick)

    def _tick(self) -> None:
        self.timer_after_id = None

        if not self.is_running or self.config is None:
            return

        if self.remaining_seconds > 0:
            self.remaining_seconds -= 1
            self._update_timer_display()

        if self.remaining_seconds == 0:
            self._advance_phase()

        if self.is_running:
            self._schedule_tick()

    def _advance_phase(self) -> None:
        if self.config is None:
            return

        # Advance through zero-length rests immediately so the timer never appears stuck.
        while True:
            if self.phase == "work":
                self.store.record_work_session(self.config.work_minutes)
                self._refresh_stats()

                if self.current_round >= self.config.rounds:
                    self.is_running = False
                    self.is_paused = False
                    self.phase = "complete"
                    self.start_button.configure(text="Start Session", state="normal")
                    self.pause_button.configure(text="Pause", state="disabled")
                    self.reset_button.configure(state="normal")
                    self._set_inputs_state("normal")
                    self.phase_label.configure(text="Session complete")
                    self.round_label.configure(
                        text=f"Finished {self.config.rounds} of {self.config.rounds} rounds"
                    )
                    self.status_label.configure(
                        text="Nice. Every work block was saved to the local tracker. Adjust settings or start another session when you are ready."
                    )
                    self._notify(
                        "Session complete",
                        "All deep work rounds are done.",
                    )
                    self._update_timer_display()
                    return

                self.phase = "rest"
                self.remaining_seconds = self.config.rest_minutes * 60
                if self.remaining_seconds > 0:
                    self._notify(
                        "Work block complete",
                        f"Round {self.current_round} is done. Start your break.",
                    )
                if self.remaining_seconds != 0:
                    break

            if self.phase == "rest":
                self.current_round += 1
                self.phase = "work"
                self.remaining_seconds = self.config.work_minutes * 60
                self._notify(
                    "Break complete",
                    f"Start round {self.current_round} of {self.config.rounds}.",
                )
                break

        self._update_status_text()
        self._update_timer_display()

    def _phase_title(self) -> str:
        if self.phase == "work":
            return "Deep work"
        if self.phase == "rest":
            return "Rest"
        if self.phase == "complete":
            return "Complete"
        return "Ready"

    def _update_status_text(self) -> None:
        if self.config is None:
            return

        if self.phase == "work":
            self.phase_label.configure(text="Deep work in progress")
            self.round_label.configure(
                text=f"Round {self.current_round} of {self.config.rounds}"
            )
            self.status_label.configure(
                text=f"Focus block {self.current_round} is live. Finishing it will increase today's and total completed session counts."
            )
        elif self.phase == "rest":
            self.phase_label.configure(text="Rest and reset")
            self.round_label.configure(
                text=f"Break before round {self.current_round + 1} of {self.config.rounds}"
            )
            self.status_label.configure(
                text=f"Round {self.current_round} is done. Take the break, then the next work block starts automatically."
            )

    def _update_timer_display(self) -> None:
        minutes, seconds = divmod(max(self.remaining_seconds, 0), 60)
        self.timer_label.configure(text=f"{minutes:02d}:{seconds:02d}")
        if self.phase == "ready":
            rounds = self._safe_round_value()
            self.round_label.configure(text=f"Round 1 of {rounds}")

    def _safe_round_value(self) -> int:
        try:
            rounds = int(self.rounds_var.get())
        except ValueError:
            rounds = self.saved_config.rounds
        return max(rounds, 1)

    def on_close(self) -> None:
        self._cancel_scheduled_tick()
        self.store.close()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    app = DeepWorkTimerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
