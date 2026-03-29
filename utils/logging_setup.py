"""
日志配置模块

负责初始化应用程序的日志系统
"""
import logging
import time
from pathlib import Path
from logging.handlers import TimedRotatingFileHandler

# 日志目录
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

# 日志格式
LOG_FORMAT = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')


def get_file_handler(filename: str, level=logging.DEBUG):
    """获取带轮转的文件处理器 (保留7天)"""
    file_path = LOG_DIR / filename
    # when='D', interval=1, backupCount=7 ensures 7 days retention
    handler = TimedRotatingFileHandler(
        file_path, 
        when='D', 
        interval=1, 
        backupCount=7, 
        encoding='utf-8'
    )
    handler.setLevel(level)
    handler.setFormatter(LOG_FORMAT)
    return handler


def setup_module_logger(name: str, filename: str, level=logging.DEBUG):
    """为特定模块创建独立日志文件"""
    handler = get_file_handler(filename, level)
    module_logger = logging.getLogger(name)
    module_logger.addHandler(handler)


def init_logging():
    """初始化日志系统"""
    # 移除旧的强制清理逻辑 (cleanup_old_logs)
    # 由 TimedRotatingFileHandler 自动管理生命周期
    
    # 根日志器
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    
    # 1. 控制台日志 (INFO+)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(LOG_FORMAT)
    root_logger.addHandler(console_handler)
    
    # 2. 全量调试日志 (按天轮转, 保留7天)
    root_logger.addHandler(get_file_handler('debug.log', logging.DEBUG))
    
    # 3. 错误和警告日志 (按天轮转, 保留7天)
    root_logger.addHandler(get_file_handler('errors.log', logging.WARNING))
    
    # 4. 按模块分离日志
    setup_module_logger('fetcher', 'fetcher.log')
    setup_module_logger('main', 'bot.log')
    setup_module_logger('ai', 'ai.log')
    
    # HTTP 日志级别调高，减少噪音
    logging.getLogger('httpcore').setLevel(logging.WARNING)
    logging.getLogger('httpx').setLevel(logging.WARNING)
