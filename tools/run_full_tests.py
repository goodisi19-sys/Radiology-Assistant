"""Run every unittest and print all thread stacks if one test stalls."""
import faulthandler
from pathlib import Path
import sys
import time
import unittest

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))

class TimedResult(unittest.TextTestResult):
    def startTest(self, test):
        super().startTest(test)
        self.started = time.monotonic()
        faulthandler.dump_traceback_later(150, exit=True)

    def stopTest(self, test):
        faulthandler.cancel_dump_traceback_later()
        elapsed = time.monotonic() - self.started
        if elapsed > 5:
            self.stream.writeln(f'{test.id()} took {elapsed:.1f}s')
        super().stopTest(test)

suite = unittest.defaultTestLoader.discover(str(root))
result = unittest.TextTestRunner(verbosity=2, resultclass=TimedResult).run(suite)
sys.exit(not result.wasSuccessful())
