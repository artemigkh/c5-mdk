"""Run the pure-Lua engine tests under lupa.lua51 (plain Lua 5.1, like the game).

Usage: python tests/run_lua_tests.py [test_file.lua ...]   (default: all tests/test_*.lua)
Each test file must `return { passed=, failed=, failures={...}, log={...} }`.
Exit code 0 when every test passes.
"""
import glob
import os
import sys

import lupa.lua51 as lupa

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ENGINE = os.path.join(ROOT, "engine")


def run_file(path):
    L = lupa.LuaRuntime(unpack_returned_tuples=True)
    L.execute("package.path = [[%s/?.lua;%s/?.lua;]] .. package.path"
              % (ENGINE.replace("\\", "/"), HERE.replace("\\", "/")))
    assert "Lua 5.1" in L.eval("_VERSION"), L.eval("_VERSION")
    res = L.execute("return dofile([[%s]])" % path.replace("\\", "/"))
    passed, failed = int(res.passed), int(res.failed)
    name = os.path.basename(path)
    for line in res.log.values():
        print("  [%s] %s" % (name, line))
    for f in res.failures.values():
        print("  FAIL [%s] %s" % (name, f))
    print("%s: %d passed, %d failed" % (name, passed, failed))
    return failed


def main(argv):
    files = argv or sorted(glob.glob(os.path.join(HERE, "test_*.lua")))
    total_failed = sum(run_file(f) for f in files)
    return 1 if total_failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
