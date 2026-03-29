"""
命令处理器包

每个命令处理器负责单一命令或相关命令组
"""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.telegram_bot.client import TelegramClient
    from utils.db import DB
