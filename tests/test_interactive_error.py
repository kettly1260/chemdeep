
import unittest
import threading
import time
from unittest.mock import MagicMock, patch
from apps.telegram_bot.services.interaction_manager import InteractionManager
from core.services.research.core_types import IterativeResearchState, ProblemSpec
from core.services.research.hypothesis_generator import generate_hypotheses

class TestInteractiveError(unittest.TestCase):
    def test_interaction_manager_flow(self):
        im = InteractionManager.get_instance()
        chat_id = 999
        
        # 1. Request
        event = im.request_interaction(chat_id)
        self.assertTrue(im.has_pending(chat_id))
        self.assertFalse(event.is_set())
        
        # 2. Simulate User Click (Async)
        def user_click():
            time.sleep(0.1)
            im.resolve_interaction(chat_id, "Retry")
            
        t = threading.Thread(target=user_click)
        t.start()
        
        # 3. Wait
        signaled = event.wait(timeout=1.0)
        self.assertTrue(signaled)
        
        # 4. Get Result
        res = im.get_result(chat_id)
        self.assertEqual(res, "Retry")
        self.assertFalse(im.has_pending(chat_id))
        t.join()

    @patch('core.services.research.hypothesis_generator.simple_chat')
    def test_hypothesis_retry_logic(self, mock_chat):
        # Setup state
        state = IterativeResearchState(
            problem_spec=ProblemSpec(
                goal="test", research_object="obj", control_variables=["v1"]
            )
        )
        
        # Mock simple_chat to fail twice then succeed
        # Side effect: raises exception, raises exception, returns valid json
        mock_chat.side_effect = [
            Exception("Timeout 1"),
            Exception("Timeout 2"),
            '[{"hypothesis_id": "H1", "mechanism_description": "Success"}]'
        ]
        
        # Callback that always says "重试"
        call_count = 0
        def cb(prompt, options):
            nonlocal call_count
            call_count += 1
            return "重试"
            
        # Run
        state = generate_hypotheses(state, interaction_callback=cb)
        
        # Assertions
        self.assertEqual(call_count, 2) # Called twice for 2 failures
        self.assertEqual(len(state.hypothesis_set.hypotheses), 1)
        self.assertEqual(state.hypothesis_set.hypotheses[0].hypothesis_id, "H1")
        
    @patch('core.services.research.hypothesis_generator.simple_chat')
    def test_hypothesis_abort_logic(self, mock_chat):
        # Setup state
        state = IterativeResearchState(
            problem_spec=ProblemSpec(
                goal="test", research_object="obj", control_variables=["v1"]
            )
        )
        
        mock_chat.side_effect = Exception("Fatal Error")
        
        def cb(prompt, options):
            return "终止"
            
        with self.assertRaisesRegex(Exception, "Fatal Error"):
            generate_hypotheses(state, interaction_callback=cb)

if __name__ == '__main__':
    unittest.main()
