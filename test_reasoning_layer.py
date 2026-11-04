"""Include the optional reasoning package in the standard repository test run."""
from pathlib import Path
import unittest

def load_tests(loader, standard_tests, pattern):
    tests = str(Path(__file__).parent / 'reasoning_layer' / 'tests')
    return unittest.TestLoader().discover(tests, pattern='test_*.py', top_level_dir=tests)
