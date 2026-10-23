#!/bin/bash
# Start the Neolatino Telegram bot in its virtual environment
cd "$(dirname "$0")"
source .venv/bin/activate
python3 bot.py
