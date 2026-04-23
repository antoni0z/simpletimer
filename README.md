# Deep Work Timer

Deep Work Timer is a small local-first macOS desktop timer for structured focus sessions. It uses only Python standard library modules, so there are no external package dependencies to install before running it.

The app does not make network requests, does not execute shell commands, and keeps all session data on the local machine.

## What It Uses

- `tkinter` for the desktop GUI
- `sqlite3` for local session and settings storage
- `unittest` for regression tests
- `osascript` and `afplay` for macOS notifications and sound alerts

## Features

- configurable work, rest, and round lengths
- local session tracking with daily, weekly, and total stats
- visible macOS alerts plus sound notifications
- persisted settings in SQLite
- no account, sync, or cloud dependency

## Clone

```bash
git clone https://github.com/antoni0z/simpletimer.git
cd simpletimer
```

## Run

```bash
python3 timer.py
```

## Tests

```bash
python3 -m unittest discover -s tests
```

## Download

You can either run the app locally with Python or download the macOS build artifact from GitHub Actions.

## Build A macOS App

```bash
python3 -m pip install -r requirements-build.txt
python3 -m PyInstaller --clean --noconfirm deep_work_timer.spec
```

The app bundle is written to `dist/Deep Work Timer.app`.

## CI/CD

- GitHub Actions publishes a macOS zip artifact for successful builds.
- Tags like `v1.0.0` also publish a GitHub release.

## Notes

- The app stores local data in `~/Library/Application Support/DeepWorkTimer/timer.db` on macOS.
- Settings are validated on load, so malformed local config values fall back to safe defaults instead of crashing the app.
- Input values are capped to reasonable limits: work/rest up to 24 hours, rounds up to 100.
- This project currently targets macOS because notifications are implemented with `osascript`.
