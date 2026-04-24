import unittest
from datetime import date, datetime
from unittest.mock import Mock, patch

from store import MAX_REST_MINUTES, MAX_ROUNDS, MAX_WORK_MINUTES, TimerConfig
from timer import DAY_CHANGE_CHECK_MS, DeepWorkTimerApp


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
        app.day_change_after_id = None
        app.is_running = True
        app.phase = "work"
        app.current_round = 1
        app.remaining_seconds = 25 * 60
        app.stats_date = date(2026, 4, 23)
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
        app.current_round = 3
        app.config = TimerConfig(25, 5, 3)
        app._update_timer_display = Mock()

        app.reset_session()

        self.assertEqual(app.root.cancelled, ["after-9"])
        self.assertFalse(app.is_running)
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

    def test_day_change_check_refreshes_stats_and_reschedules(self) -> None:
        app = self.make_app()
        app._refresh_stats = Mock()

        with patch("timer.datetime") as fake_datetime:
            fake_datetime.now.return_value = datetime(2026, 4, 24, 0, 1, 0)
            app._check_for_day_change()

        app._refresh_stats.assert_called_once_with()
        self.assertEqual(app.root.after_calls[0][0], DAY_CHANGE_CHECK_MS)
        self.assertEqual(app.timer_after_id, None)
        self.assertEqual(app.day_change_after_id, "after-1")

    def test_pause_cancels_scheduled_tick(self) -> None:
        app = self.make_app()
        app.timer_after_id = "after-3"

        app.toggle_pause()

        self.assertFalse(app.is_running)
        self.assertEqual(app.root.cancelled, ["after-3"])
        self.assertEqual(app.pause_button.options["text"], "Resume")
        self.assertEqual(app.start_button.options["text"], "Resume")
        self.assertEqual(app.start_button.options["state"], "normal")

    def test_on_close_cancels_timer_and_day_change_callbacks(self) -> None:
        app = self.make_app()
        app.timer_after_id = "after-3"
        app.day_change_after_id = "after-4"

        app.on_close()

        self.assertEqual(app.root.cancelled, ["after-3", "after-4"])
        app.store.close.assert_called_once_with()


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
            (
                str(MAX_WORK_MINUTES + 1),
                "10",
                "4",
                f"Work minutes must be {MAX_WORK_MINUTES} or less.",
            ),
            (
                "25",
                str(MAX_REST_MINUTES + 1),
                "4",
                f"Rest minutes must be {MAX_REST_MINUTES} or less.",
            ),
            (
                "25",
                "10",
                str(MAX_ROUNDS + 1),
                f"Rounds must be {MAX_ROUNDS} or less.",
            ),
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
