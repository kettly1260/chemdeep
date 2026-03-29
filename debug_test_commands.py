
import unittest
import sys
import traceback

try:
    from tests.test_bot_commands import TestBotCommands
    suite = unittest.TestLoader().loadTestsFromTestCase(TestBotCommands)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if not result.wasSuccessful():
        print("FAILURES/ERRORS:")
        for f in result.failures:
            print(f)
        for e in result.errors:
            print(e[0])
            print(e[1])
        sys.exit(1)
except Exception:
    traceback.print_exc()
    sys.exit(1)
