
import unittest
import sys
import io

# Buffer stdout
buffer = io.StringIO()
sys.stdout = buffer

try:
    from tests.test_bot_commands import TestBotCommands
    suite = unittest.TestLoader().loadTestsFromTestCase(TestBotCommands)
    runner = unittest.TextTestRunner(stream=buffer, verbosity=2)
    result = runner.run(suite)
    
    with open("test_result.txt", "w", encoding="utf-8") as f:
        f.write(buffer.getvalue())
        
        if not result.wasSuccessful():
            f.write("\nFAILURES/ERRORS:\n")
            for fails in result.failures:
                f.write(str(fails[0]) + "\n")
                f.write(str(fails[1]) + "\n")
            for errs in result.errors:
                f.write(str(errs[0]) + "\n")
                f.write(str(errs[1]) + "\n")
    
    # Print simple status to stdout (safe)
    print("DONE. See test_result.txt")

except Exception as e:
    sys.stdout = sys.__stdout__
    print(e)
    sys.exit(1)
