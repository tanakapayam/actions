"""A caller-supplied smoke test: argv is <distribution name> <import name> <version>."""

import importlib
import sys

module = importlib.import_module(sys.argv[2])
assert module.greet("actions") == "hello, actions"
print("greet works")
