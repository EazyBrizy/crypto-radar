# Development Rules (STRICT)

This project uses AI-assisted development (Cursor).
All generated code MUST follow these rules.

---

# 1. Interfaces (CRITICAL)

- ALWAYS follow docs/interfaces.md
- DO NOT change function signatures
- DO NOT rename fields
- DO NOT change data structures

If a change is required:
→ update interfaces.md FIRST
→ then implement

---

# 2. Architecture

Follow clean architecture:

- api/ → only request/response handling
- services/ → business logic
- strategies/ → trading logic only
- models/ → data models only

STRICTLY FORBIDDEN:
- business logic inside api/
- database calls inside strategies/
- mixing responsibilities

---

# 3. Functions

All functions MUST:

- use type hints
- have clear input/output
- be deterministic (no hidden state)
- be small and focused

---

# 4. Secrets

- NEVER log API keys
- NEVER print secrets
- NEVER expose keys in responses
- ALWAYS use environment variables

DO NOT invent new business logic
ONLY implement explicitly defined logic

Example:

```python
async def calculate_features(market_data: dict) -> dict: