import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from timer import DeepWorkTimerApp, SessionStore, TimerConfig


class FakeWidget:
    def __init__(self) -> None:
        self.options = {}

    def configure(self, **kwargs: object) -> None:
        self.options.update(kwargs)


class FakeVar:
    def __init__(self, value: str) -> None:
        self.value = value

    def get(self) -> str:
        return self.value


class FakeRoot:
    def __init__(self) -> None:
        self.after_calls = []
        self.cancelled = []

    def after(self, delay: int, callback: object) -> str:
        token = f"after-{len(self.after_calls) + 1}"
        self.after_calls.append((delay, callback))
        return token

    def after_cancel(self, token: str) -> None:
        self.cancelled.append(token)

    def winfo_children(self) -> list[object]:
        return []

    def destroy(self) -> None:
        return None


class SessionStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_timer.db"
        self.store = SessionStore(self.db_path)

    def tearDown(self) -> None:
        self.store.close()
        self.temp_dir.cleanup()

    def _insert_session(self, completed_at: datetime, work_minutes: int) -> None:
        self.store.connection.execute(
            "INSERT INTO sessions(completed_at, work_minutes) VALUES (?, ?)",
            (completed_at.strftime("%Y-%m-%d %H:%M:%S"), work_minutes),
        )
        self.store.connection.commit()

    def test_default_config_is_returned_when_settings_are_empty(self) -> None:
        self.assertEqual(self.store.get_saved_config(), TimerConfig(50, 10, 4))

    def test_saved_config_round_trips_exactly(self) -> None:
        config = TimerConfig(work_minutes=90, rest_minutes=15, rounds=3)

        self.store.save_config(config)

        self.assertEqual(self.store.get_saved_config(), config)

    def test_empty_store_reports_zero_stats(self) -> None:
        stats = self.store.get_stats()

        self.assertEqual(stats.daily_sessions, 0)
        self.assertEqual(stats.total_sessions, 0)
        self.assertEqual(stats.daily_minutes, 0)
        self.assertEqual(stats.weekly_average_minutes, 0.0)
        self.assertEqual(stats.total_minutes, 0)
        self.assertEqual(stats.sessions_per_day_last_week, 0.0)
        self.assertEqual(stats.average_minutes_per_day_last_week, 0.0)

    def test_record_work_session_updates_daily_and_total_stats(self) -> None:
        self.store.record_work_session(15)

        stats = self.store.get_stats()

        self.assertEqual(stats.daily_sessions, 1)
        self.assertEqual(stats.total_sessions, 1)
        self.assertEqual(stats.daily_minutes, 15)
        self.assertEqual(stats.total_minutes, 15)
        self.assertAlmostEqual(stats.sessions_per_day_last_week, 1 / 7)
        self.assertAlmostEqual(stats.average_minutes_per_day_last_week, 15 / 7)

    def test_stats_respect_time_windows_and_totals(self) -> None:
        now = datetime.now()
        self._insert_session(now, 25)
        self._insert_session(now - timedelta(days=2), 35)
        self._insert_session(now - timedelta(days=8), 40)

        stats = self.store.get_stats()

        self.assertEqual(stats.daily_sessions, 1)
        self.assertEqual(stats.total_sessions, 3)
        self.assertEqual(stats.daily_minutes, 25)
        self.assertEqual(stats.total_minutes, 100)
        self.assertAlmostEqual(stats.weekly_average_minutes, 50.0)
        self.assertAlmostEqual(stats.sessions_per_day_last_week, 2 / 7)
        self.assertAlmostEqual(stats.average_minutes_per_day_last_week, 60 / 7)


class FormattingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = DeepWorkTimerApp.__new__(DeepWorkTimerApp)

    def test_format_hours_keeps_small_values_visible(self) -> None:
        self.assertEqual(self.app._format_hours(2), "0.03h")
        self.assertEqual(self.app._format_hours(0), "0.00h")
        self.assertEqual(self.app._format_hours(90), "1.5h")

    def test_format_duration_is_human_readable(self) -> None:
        self.assertEqual(self.app._format_duration(0), "0m")
        self.assertEqual(self.app._format_duration(2), "2m")
        self.assertEqual(self.app._format_duration(60), "1h")
        self.assertEqual(self.app._format_duration(90), "1h 30m")


class TimerBehaviorTests(unittest.TestCase):
    def make_app(self) -> DeepWorkTimerApp:
        app = DeepWorkTimerApp.__new__(DeepWorkTimerApp)
        app.root = FakeRoot()
        app.store = Mock()
        app.saved_config = TimerConfig(50, 10, 4)
        app.config = TimerConfig(25, 5, 3)
        app.timer_after_id = None
        app.is_running = True
        app.is_paused = False
        app.phase = "work"
        app.current_round = 1
        app.remaining_seconds = 25 * 60
        app.start_button = FakeWidget()
        app.pause_button = FakeWidget()
        app.reset_button = FakeWidget()
        app.phase_label = FakeWidget()
        app.round_label = FakeWidget()
        app.status_label = FakeWidget()
        app.timer_label = FakeWidget()
        app.rounds_var = FakeVar("4")
        app._refresh_stats = Mock()
        app._notify = Mock()
        app._update_status_text = Mock()
        app._update_timer_display = Mock()
        app._set_inputs_state = Mock()
        app._get_config_from_inputs = Mock(return_value=TimerConfig(30, 5, 2))
        return app

    def test_work_phase_records_one_session_and_enters_rest(self) -> None:
        app = self.make_app()

        app._advance_phase()

        app.store.record_work_session.assert_called_once_with(25)
        app._refresh_stats.assert_called_once_with()
        self.assertEqual(app.phase, "rest")
        self.assertEqual(app.current_round, 1)
        self.assertEqual(app.remaining_seconds, 5 * 60)
        app._notify.assert_called_once_with(
            "Work block complete",
            "Round 1 is done. Start your break.",
        )
        app._update_status_text.assert_called_once_with()
        app._update_timer_display.assert_called_once_with()

    def test_final_round_completes_session(self) -> None:
        app = self.make_app()
        app.config = TimerConfig(25, 5, 2)
        app.current_round = 2

        app._advance_phase()

        app.store.record_work_session.assert_called_once_with(25)
        self.assertFalse(app.is_running)
        self.assertFalse(app.is_paused)
        self.assertEqual(app.phase, "complete")
        self.assertEqual(app.start_button.options["state"], "normal")
        self.assertEqual(app.pause_button.options["state"], "disabled")
        self.assertEqual(app.reset_button.options["state"], "normal")
        app._set_inputs_state.assert_called_once_with("normal")
        app._notify.assert_called_once_with(
            "Session complete",
            "All deep work rounds are done.",
        )
        app._update_status_text.assert_not_called()
        app._update_timer_display.assert_called_once_with()

    def test_zero_rest_skips_directly_to_next_work_round(self) -> None:
        app = self.make_app()
        app.config = TimerConfig(25, 0, 3)

        app._advance_phase()

        app.store.record_work_session.assert_called_once_with(25)
        self.assertEqual(app.phase, "work")
        self.assertEqual(app.current_round, 2)
        self.assertEqual(app.remaining_seconds, 25 * 60)
        app._notify.assert_called_once_with(
            "Break complete",
            "Start round 2 of 3.",
        )

    def test_rest_phase_advances_to_next_work_round_and_notifies(self) -> None:
        app = self.make_app()
        app.phase = "rest"
        app.current_round = 1

        app._advance_phase()

        self.assertEqual(app.phase, "work")
        self.assertEqual(app.current_round, 2)
        self.assertEqual(app.remaining_seconds, 25 * 60)
        app._notify.assert_called_once_with(
            "Break complete",
            "Start round 2 of 3.",
        )

    def test_reset_returns_to_ready_state(self) -> None:
        app = self.make_app()
        app.timer_after_id = "after-9"
        app.phase = "work"
        app.is_running = True
        app.is_paused = True
        app.current_round = 3
        app.config = TimerConfig(25, 5, 3)
        app._update_timer_display = Mock()

        app.reset_session()

        self.assertEqual(app.root.cancelled, ["after-9"])
        self.assertFalse(app.is_running)
        self.assertFalse(app.is_paused)
        self.assertEqual(app.phase, "ready")
        self.assertIsNone(app.config)
        self.assertEqual(app.current_round, 1)
        self.assertEqual(app.remaining_seconds, 30 * 60)
        app._get_config_from_inputs.assert_called_once_with(show_errors=False)
        app._set_inputs_state.assert_called_once_with("normal")
        self.assertEqual(app.start_button.options["text"], "Start Session")
        self.assertEqual(app.start_button.options["state"], "normal")
        self.assertEqual(app.pause_button.options["state"], "disabled")
        self.assertEqual(app.reset_button.options["state"], "disabled")

    def test_tick_decrements_remaining_seconds_and_reschedules(self) -> None:
        app = self.make_app()
        app.remaining_seconds = 5
        app._advance_phase = Mock()

        app._tick()

        self.assertEqual(app.remaining_seconds, 4)
        app._update_timer_display.assert_called_once_with()
        app._advance_phase.assert_not_called()
        self.assertEqual(app.root.after_calls[0][0], 1000)
        self.assertEqual(app.timer_after_id, "after-1")

    def test_tick_advances_phase_at_zero(self) -> None:
        app = self.make_app()
        app.remaining_seconds = 1
        app._advance_phase = Mock()

        app._tick()

        self.assertEqual(app.remaining_seconds, 0)
        app._advance_phase.assert_called_once_with()

    def test_pause_cancels_scheduled_tick(self) -> None:
        app = self.make_app()
        app.timer_after_id = "after-3"

        app.toggle_pause()

        self.assertFalse(app.is_running)
        self.assertTrue(app.is_paused)
        self.assertEqual(app.root.cancelled, ["after-3"])
        self.assertEqual(app.pause_button.options["text"], "Resume")
        self.assertEqual(app.start_button.options["text"], "Resume")
        self.assertEqual(app.start_button.options["state"], "normal")


class InputValidationTests(unittest.TestCase):
    def make_app(self, work: str, rest: str, rounds: str) -> DeepWorkTimerApp:
        app = DeepWorkTimerApp.__new__(DeepWorkTimerApp)
        app.work_var = FakeVar(work)
        app.rest_var = FakeVar(rest)
        app.rounds_var = FakeVar(rounds)
        app.saved_config = TimerConfig(50, 10, 4)
        return app

    def test_invalid_inputs_are_rejected(self) -> None:
        cases = [
            ("0", "10", "4", "Work minutes must be greater than 0."),
            ("25", "-1", "4", "Rest minutes cannot be negative."),
            ("25", "10", "0", "Rounds must be greater than 0."),
            ("abc", "10", "4", "Use whole numbers for all fields."),
        ]

        for work, rest, rounds, message in cases:
            app = self.make_app(work, rest, rounds)
            with self.subTest(work=work, rest=rest, rounds=rounds), patch(
                "timer.messagebox.showerror"
            ) as showerror:
                self.assertIsNone(app._get_config_from_inputs())
                showerror.assert_called_once_with("Invalid settings", message)


if __name__ == "__main__":
    unittest.main()
