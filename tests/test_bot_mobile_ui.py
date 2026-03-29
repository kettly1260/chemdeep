
import unittest
from unittest.mock import MagicMock, patch
from apps.telegram_bot.ui.keyboards import build_models_keyboard, build_config_keyboard, build_run_actions_keyboard, build_help_menu
from apps.telegram_bot.ui.cards import render_run_card, render_config_card
from apps.telegram_bot.handlers.callback_handler import handle_callback_query
from apps.telegram_bot.command_registry import CommandRegistry

class TestMobileUX(unittest.TestCase):
    def test_keyboards_logic(self):
        # 1. Models Pagination
        models = [f"m{i}" for i in range(20)]
        kb1 = build_models_keyboard(models, "m0", page=1, page_size=8)
        # Should have m0..m7 (8 items -> 4 rows) + Nav + Actions
        # Check integrity
        rows = kb1["inline_keyboard"]
        self.assertTrue(len(rows) >= 4)
        self.assertIn("cmd:/model set m0", str(rows))
        self.assertIn("✅ m0", str(rows)) # Current
        self.assertIn("使用 m1", str(rows)) # Other
        
        # Page 2
        kb2 = build_models_keyboard(models, "m0", page=2, page_size=8)
        self.assertIn("cmd:/model set m8", str(kb2))
        self.assertIn("⬅️ 上一页", str(kb2))
        
        # 2. Config
        kb_cfg = build_config_keyboard()
        self.assertIn("interact:key", str(kb_cfg))
        self.assertIn("🤖 切换模型", str(kb_cfg))
        
    def test_cards_rendering(self):
        # Run Card
        job = {"job_id": "123", "status": "running", "goal": "G", "created_at": "now", "message": "msg"}
        card = render_run_card(job)
        self.assertIn("🏃", card)
        self.assertIn("123", card)
        self.assertIn("💡 提示", card)
        
        # Config Card
        cfg_mock = MagicMock()
        cfg_mock.model = "gpt-4"
        cfg_mock.masked_key.return_value = "sk-***"
        card_cfg = render_config_card(cfg_mock)
        self.assertIn("gpt-4", card_cfg)
        self.assertIn("💡 提示", card_cfg)
        
    @patch('apps.telegram_bot.handlers.callback_handler.registry')
    def test_callback_routing(self, mock_registry):
        # Test cmd: routing
        tg = MagicMock()
        db = MagicMock()
        settings = MagicMock()
        settings.TELEGRAM_ALLOWED_CHAT_IDS = [123]
        
        cb = {
            "id": "1", "data": "cmd:/models page 2",
            "message": {"chat": {"id": 123}, "message_id": 999},
            "from": {"id": 123}
        }
        
        handle_callback_query(cb, tg, db, settings)
        
        # Verify dispatch called with stripped command
        mock_registry.dispatch.assert_called_with("/models page 2", unittest.mock.ANY)
        
    @patch('apps.telegram_bot.handlers.callback_handler.registry')
    def test_help_routing(self, mock_registry):
        tg = MagicMock()
        db = MagicMock()
        settings = MagicMock()
        settings.TELEGRAM_ALLOWED_CHAT_IDS = [123]
        
        cb = {
            "id": "1", "data": "help:Config",
            "message": {"chat": {"id": 123}},
            "from": {"id": 123}
        }
        
        handle_callback_query(cb, tg, db, settings)
        mock_registry.dispatch.assert_called_with("/help Config", unittest.mock.ANY)

    def test_help_refactor_logic(self):
        # We need to test the logic inside commands/basic.py -> cmd_help
        # But that requires importing cmd_help and setting up payload/ctx
        # Let's import it via registry if possible, or direct import
        from apps.telegram_bot.commands.basic import register_basic_commands
        registry = CommandRegistry()
        register_basic_commands(registry)
        
        # 1. Test Default Menu (No Args)
        ctx = {"tg": MagicMock(), "chat_id": 123, "user_id": 1, "db": MagicMock()}
        registry.dispatch("/help", ctx)
        
        # Should call send_message with menu text, NOT full help
        args, kwargs = ctx["tg"].send_message.call_args
        self.assertIn("帮助菜单", args[1])
        self.assertNotIn("/help -", args[1]) # Shouldn't show command list
        self.assertIn("inline_keyboard", kwargs["reply_markup"])
        
        # 2. Test Group Filter (Alias)
        ctx["tg"].reset_mock()
        registry.dispatch("/help 配置", ctx)
        args, kwargs = ctx["tg"].send_message.call_args
        self.assertIn("Help: Config", args[1])
        self.assertIn("/config", args[1]) # Should show config command
        self.assertNotIn("/run", args[1]) # Should NOT show execution command
        
        # 3. Test All
        ctx["tg"].reset_mock()
        registry.dispatch("/help all", ctx)
        args, kwargs = ctx["tg"].send_message.call_args
        # Registry output contains "Basic" group header usually
        self.assertIn("Basic", args[1]) 
        self.assertIn("/help", args[1]) # /help IS registered 

if __name__ == '__main__':
    unittest.main()
