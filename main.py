"""
ChemDeep 入口文件

启动 Telegram Bot 或执行 CLI 命令
"""
import typer

# 初始化日志
from utils.logging_setup import init_logging
init_logging()

import logging
logger = logging.getLogger('main')

# 创建 Typer 应用
app = typer.Typer(no_args_is_help=True)


@app.command("bot")
def run_bot():
    """启动 Telegram Bot（主流程）"""
    from apps.telegram_bot.runner import BotRunner
    
    runner = BotRunner()
    runner.run()


# 注册 CLI 命令
from core.cli_commands import register_cli_commands
register_cli_commands(app)


if __name__ == "__main__":
    app()
