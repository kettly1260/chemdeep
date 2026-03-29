# Telegram Bot App

This directory contains the Telegram Bot application for ChemDeep.

## Purpose

Provides a chat interface for controlling the Deep Research agent.

## Usage

### Start the Bot

From the project root:

```bash
# Method 1 (Direct module execution)
python -m apps.telegram_bot.main

# Method 2 (Root entry point)
python tg_bot.py
```

### Configuration

Configuration is read from the root `.env` file. Ensure `TELEGRAM_TOKEN` and `TELEGRAM_ALLOWED_CHAT_IDS` are set.

## Output Artifacts

- **Uploads**: Files uploaded to the bot are saved in `library/uploads/` (or configured `LIBRARY_DIR`).
- **Runs**: Research run artifacts are stored in `runs/<run_id>/`.

## Structure

- `client.py`: Wrapper for Telegram Bot API (httpx).
- `runner.py`: Main bot loop and update handling.
- `handlers/`: Logic for processing messages and callbacks.
  - `message_router.py`: Routes text commands to `core.commands`.
  - `callback_handler.py`: Handles button clicks.
- `main.py`: Entry point.
