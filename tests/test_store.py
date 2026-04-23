import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from store import (
    DEFAULT_CONFIG,
    MAX_ROUNDS,
    MAX_WORK_MINUTES,
    SessionStore,
    TimerConfig,
)


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
        self.assertEqual(self.store.get_saved_config(), DEFAULT_CONFIG)

    def test_invalid_saved_settings_fall_back_to_defaults(self) -> None:
        with self.store.connection:
            self.store.connection.executemany(
                "INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)",
                [
                    ("work_minutes", "abc"),
                    ("rest_minutes", "-5"),
                    ("rounds", str(MAX_ROUNDS + 1)),
                ],
            )

        self.assertEqual(self.store.get_saved_config(), DEFAULT_CONFIG)

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

    def test_record_work_session_rejects_out_of_range_values(self) -> None:
        with self.assertRaises(ValueError):
            self.store.record_work_session(0)

        with self.assertRaises(ValueError):
            self.store.record_work_session(MAX_WORK_MINUTES + 1)

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


if __name__ == "__main__":
    unittest.main()
