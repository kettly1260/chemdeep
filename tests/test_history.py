import sys
import unittest
from pathlib import Path
import json
import shutil
import logging

# Add project root to path
sys.path.append(str(Path("F:/YING/Documents/chemdeep")))

from core.execution.history import RunHistoryIndex
from config.settings import settings

logging.basicConfig(level=logging.INFO)

class TestRunHistory(unittest.TestCase):
    def setUp(self):
        # Use a temporary file for testing
        self.test_history_path = settings.BASE_DIR / "data" / "test_run_history.json"
        
        # Override the history file path in the class instance if possible, 
        # but pure RunHistoryIndex uses settings.DATA_DIR / "run_history.json"
        # Since I can't easily injection-override a global setting without side effects,
        # I will instantiate RunHistoryIndex and then manually patch its file attributes if needed.
        # But looking at core/execution/history.py, it likely hardcodes the path in __init__?
        # Let's check history.py logic.
        
        # Mocking the settings.BASE_DIR or DATA_DIR would be ideal.
        # But for now, let's just inspect the class behavior.
        self.history = RunHistoryIndex()
        # Patch the path correctly (it's a class attribute used as instance attribute)
        self.history.INDEX_FILE = self.test_history_path
        # Force reload from empty/new path (since init loaded from default)
        self.history._index = {}
        
        if self.test_history_path.exists():
            self.test_history_path.unlink()
            
    def tearDown(self):
        if self.test_history_path.exists():
            self.test_history_path.unlink()

    def test_add_and_find_match(self):
        # 1. Add a completed run
        goal = "Synthesize B(9,12)-(pyren-5-yl-thiophene-2)2-o-carborane as Fe3+ probe"
        run_id = "test_run_001"
        self.history.add_run(goal, run_id, "completed", "Summary text")
        
        # 2. Check if file exists
        self.assertTrue(self.test_history_path.exists(), "History file was not created")
        
        # 3. Try to find match with exact string
        match = self.history.find_match(goal)
        print(f"Exact match result: {match}")
        self.assertIsNotNone(match, "Should find exact match")
        self.assertEqual(match["run_id"], run_id)
    
    def test_loose_matching_limitations(self):
        # Verify current limitation: punctuation differences cause mismatch
        goal = "Test Goal with Punctuation?"
        run_id = "run_punct"
        self.history.add_run(goal, run_id, "completed", "summary")
        
        goal_no_punct = "Test Goal with Punctuation"
        match = self.history.find_match(goal_no_punct)
        
        # Currently expected to FAIL (return None) because normalization is strict
        # We want to change this behavior later, but for now assert it matches (will fail)
        # OR assert it is None to confirm current state.
        # Let's assert it DOES match, so the test fails, confirming we need to fix it.
        self.assertIsNotNone(match, "Should match even without punctuation (Simulating User Issue)")
        
if __name__ == "__main__":
    unittest.main()
