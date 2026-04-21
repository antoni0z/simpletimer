# Deep Work Timer

Deep Work Timer is a small local-first macOS desktop timer for structured focus sessions. It uses only Python standard library modules, so there are no external package dependencies to install before running it.

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

## Notes

- The app stores local data in `timer.db` next to the script.
- `timer.db` is ignored by git so personal session history is not committed.
- This project currently targets macOS.
