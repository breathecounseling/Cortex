"""
Simple REPL loop for Cortex Executor
"""

from executor.connectors.openai_client import ask_executor

def main():
    print("Cortex Executor REPL (type 'quit' to exit)")
    while True:
        try:
            user = input("You: ").strip()
            if not user or user.lower() in ("quit", "exit"):
                break
            result = ask_executor(user)

            # Handle chat responses
            if result.get("status") == "ok" and "assistant_output" in result:
                print("Executor:", result["assistant_output"])

            # Handle builder/extender/tool responses
            elif result.get("status") in ("ok", "function_call"):
                print("Executor [tool]:", result.get("message") or result)

            # Handle errors
            else:
                print("Executor [error]:", result.get("message") or result)

        except (KeyboardInterrupt, EOFError):
            break

if __name__ == "__main__":
    main()
