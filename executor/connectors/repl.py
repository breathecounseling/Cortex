# repl.py
from __future__ import annotations
import sys

from executor.plugins.extend_plugin import extend_plugin
from executor.plugins.error_handler import ExecutorError

BANNER = "Executor REPL — type: extend <plugin> : <goal> | quit"

def main():
    print(BANNER)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        if line.lower() in {"quit", "exit"}:
            print("bye")
            return
        if line.startswith("extend "):
            # expected: extend <identifier> : <goal>
            try:
                _, rest = line.split(" ", 1)
                if " : " in rest:
                    plugin_identifier, goal = rest.split(" : ", 1)
                elif ":" in rest:
                    plugin_identifier, goal = rest.split(":", 1)
                else:
                    print("Usage: extend <plugin|path|module> : <goal>")
                    continue
                result = extend_plugin(plugin_identifier.strip(), goal.strip())
                print(result)
            except ExecutorError as e:
                print({"status": "error", "kind": e.kind, "details": e.details})
            except Exception as e:
                print({"status": "error", "kind": type(e).__name__, "msg": str(e)})
            continue

        print("Unknown command. Try: extend <plugin> : <goal>")

if __name__ == "__main__":
    main()