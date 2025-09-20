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
            if result.get("status") == "ok":
                print("Executor:", result["assistant_output"])
            else:
                print("Executor [error]:", result.get("message"))
        except (KeyboardInterrupt, EOFError):
            break

if __name__ == "__main__":
    main()
