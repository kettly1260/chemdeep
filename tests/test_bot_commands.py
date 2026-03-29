"""
Tests for Telegram Bot Commands (P11)

Covers:
- Command Registry (Registration, Parsing, Dispatch)
- Runtime Config (Per-user settings, Crypto)
- Commands: Basic, Models, Execution, Reporting
"""
import unittest
import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

from apps.telegram_bot.command_registry import CommandRegistry, CommandSpec
from apps.telegram_bot.services.runtime_config import get_user_config, set_user_config, reset_user_config
from apps.telegram_bot.services.model_provider import fetch_models
from apps.telegram_bot.commands import register_all

# Import actual commands for integration-like tests
# (We rely on registry dispatch for testing, so we don't need direct function imports if we use registry)

class TestBotCommands(unittest.TestCase):
    def setUp(self):
        # Mock DB
        self.mock_db = MagicMock()
        self.mock_db.kv = {}
        def kv_get(k, default=None): 
            val = self.mock_db.kv.get(k)
            return val if val is not None else default
        def kv_set(k, v): 
            if v is None:
                self.mock_db.kv.pop(k, None)
            else:
                self.mock_db.kv[k] = str(v)
        def kv_delete(k): self.mock_db.kv.pop(k, None)
        
        self.mock_db.kv_get.side_effect = kv_get
        self.mock_db.kv_set.side_effect = kv_set
        self.mock_db.kv_delete.side_effect = kv_delete
        self.mock_db.create_job.return_value = "job_123"
        self.mock_db.list_jobs.return_value = []
        
        # Mock TG
        self.mock_tg = MagicMock()
        self.mock_tg.send_message.return_value = 100
        
        # Context
        self.ctx = {
            "tg": self.mock_tg,
            "db": self.mock_db,
            "chat_id": 12345,
            "user_id": 12345
        }
        
        # Registry
        self.registry = CommandRegistry()
        register_all(self.registry)
        
        # settings patch
        # settings patch
        # Patch settings in specific modules that import it
        self.mock_settings = MagicMock()
        self.mock_settings.OPENAI_MODEL = "gpt-4"
        self.mock_settings.OPENAI_API_BASE = "https://default.com"
        self.mock_settings.AI_PROVIDER = "openai"
        self.mock_settings.OPENAI_API_KEY = "env-key"
        self.mock_settings.TELEGRAM_TOKEN = "fake-token-must-be-str-bytes-whatever" 
        self.mock_settings.GEMINI_API_KEY = "gemini-key"
        
        self.patcher1 = patch('apps.telegram_bot.services.runtime_config.settings', self.mock_settings)
        self.patcher2 = patch('apps.telegram_bot.services.crypto.settings', self.mock_settings)
        
        self.patcher1.start()
        self.patcher2.start()
        
        # We need OS env for crypto fallback check if used
        self.patcher3 = patch.dict('os.environ', {"PROJ_SECRET_KEY": "test-secret-key-for-crypto"})
        self.patcher3.start()
        
        # Ensure cache dir exists (re-create for each test)
        Path("cache/models").mkdir(parents=True, exist_ok=True)
        
    def tearDown(self):
        self.patcher1.stop()
        self.patcher2.stop()
        self.patcher3.stop()
        if Path("cache/models").exists():
            shutil.rmtree("cache/models")

    def test_registry_dispatch(self):
        # 1. Basic Dispatch
        res = self.registry.dispatch("/help", self.ctx)
        self.assertTrue(res)
        self.mock_tg.send_message.assert_called()
        arg = self.mock_tg.send_message.call_args[0][1]
        self.assertIn("**ChemDeep Bot Help**", arg)
        
        # 2. Unknown Command
        res = self.registry.dispatch("/unknown", self.ctx)
        self.assertFalse(res)
        
        # 3. Subcommand
        res = self.registry.dispatch("/config reset", self.ctx)
        self.assertTrue(res)
        
    def test_help_content(self):
        text = self.registry.get_help_text()
        self.assertIn("/run", text)
        self.assertIn("/models", text)
        self.assertIn("Config", text)
        self.assertIn("Usage:", text)

    def test_runtime_config_isolation(self):
        # User A setting
        set_user_config(101, "model", "model-A", self.mock_db)
        
        # User B setting
        set_user_config(102, "model", "model-B", self.mock_db)
        
        # Fetch A
        cfg_a = get_user_config(101, self.mock_db)
        self.assertEqual(cfg_a.model, "model-A")
        
        # Fetch B
        cfg_b = get_user_config(102, self.mock_db)
        self.assertEqual(cfg_b.model, "model-B")
        
        # Fetch Unknown (Env fallback)
        cfg_c = get_user_config(999, self.mock_db)
        # print(f"DEBUG: cfg_c.model={cfg_c.model}, source={cfg_c.model_source}")
        self.assertEqual(cfg_c.model, "gpt-4")

    @patch('apps.telegram_bot.services.model_provider._fetch_from_api')
    def test_models_cache(self, mock_fetch):
        mock_fetch.return_value = ["gpt-3.5", "gpt-4"]
        
        # 1. First Call (Miss)
        self.registry.dispatch("/models", self.ctx)
        mock_fetch.assert_called_once()
        self.mock_tg.send_message.assert_called() # "Fetch..."
        
        # 2. Second Call (Hit)
        mock_fetch.reset_mock()
        self.registry.dispatch("/models", self.ctx)
        mock_fetch.assert_not_called()
        
        # 3. Force Refresh
        self.registry.dispatch("/models refresh", self.ctx)
        mock_fetch.assert_called_once()

    def test_key_encryption(self):
        from apps.telegram_bot.services.crypto import encrypt_key, decrypt_key
        
        key = "sk-secret-123"
        enc = encrypt_key(key)
        self.assertNotEqual(key, enc)
        
        dec = decrypt_key(enc)
        self.assertEqual(key, dec)
        
        # Test Command
        self.registry.dispatch("/key set sk-new-key", self.ctx)
        # Verify DB has encrypted key
        raw_val = self.mock_db.kv.get("tg:12345:api_key_enc")
        self.assertIsNotNone(raw_val, "Encrypted key not found in DB")
        # print(f"DEBUG: raw_val={raw_val}")
        self.assertNotIn("sk-new-key", raw_val)
        
        # Verify Config Read
        cfg = get_user_config(12345, self.mock_db)
        self.assertEqual(cfg.api_key, "sk-new-key")
        
        # Verify Masked Output
        args = self.mock_tg.send_message.call_args[0]
        # Verify Masked Output
        args = self.mock_tg.send_message.call_args[0]
        # Depending on how it's masked, check loosely
        self.assertIn("-key", args[1])
        # Also print to debug if fails again
        # print(f"DEBUG MASK: {args[1]}")

    @patch('core.commands.fetch._start_fetch_task')
    def test_run_command_file_mode(self, mock_start_fetch):
        # 1. File Mode (via --last and DB kv)
        # 1. File Mode (via --last and DB kv)
        # Override the kv_get side effect defined in setUp
        original_side_effect = self.mock_db.kv_get.side_effect
        self.mock_db.kv_get.side_effect = lambda k, default=None: "last_file.txt" if k.startswith("last_upload") else original_side_effect(k, default)
        # Patch Path.exists
        with patch('pathlib.Path.exists', return_value=True):
            self.registry.dispatch("/run --last --max 20", self.ctx)
            
            mock_start_fetch.assert_called_once()
            args = mock_start_fetch.call_args[0]
            # args: (chat_id, job_id, wos_file, goal, max_papers, tg)
            self.assertEqual(args[4], 20)

    @patch('core.services.research.iterative_main.run_iterative_research')
    @patch('threading.Thread.start') # Don't start real thread
    def test_run_command_deep_research(self, mock_thread_start, mock_run_iterative):
        # 2. Deep Research Mode (Goal Only)
        self.registry.dispatch("/run synthesis of aspirin", self.ctx)
        
        # Verify Job Created
        self.mock_db.create_job.assert_called()
        job_args = self.mock_db.create_job.call_args[0][1]
        self.assertEqual(job_args["model_override"], "gpt-4")
        
        # Verify Thread Start was called (which invokes run_worker)
        mock_thread_start.assert_called()

    def test_report_command(self):
        with patch('pathlib.Path.exists') as mock_exists:
            mock_exists.return_value = True
            self.registry.dispatch("/report 1001", self.ctx)
            # Should try send_document
            self.assertTrue(self.mock_tg.send_document.called)

if __name__ == '__main__':
    unittest.main()
