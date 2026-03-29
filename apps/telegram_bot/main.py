"""
Telegram Bot App Entry Point
"""
from utils.logging_setup import init_logging

def main():
    """Start the Telegram Bot"""
    # Initialize logging first
    init_logging()
    
    from .runner import BotRunner
    runner = BotRunner()
    runner.run()

if __name__ == "__main__":
    main()
