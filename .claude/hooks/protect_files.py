import sys
import json

data = json.load(sys.stdin)
cmd = data.get("tool_input", {}).get("command", "")

protected = ["spendly.db", "spendly - Copy.db", ".env", "migrations/"]
dangerous = ["rm ", "rm -", "unlink ", "truncate ", "Remove-Item", "remove-item", "del ", "ri "]

for d in dangerous:
    if d in cmd:
        for p in protected:
            if p in cmd:
                print(f"BLOCKED: Cannot run destructive command on protected file: {p}", file=sys.stderr)
                sys.exit(2)
