# Provider Development

`moyu-tg-relay` separates the Telegram transport and request lifecycle from provider-specific business rules.

## Architecture

```text
Telegram / Telethon
      ↓
Relay Core
  - session lifecycle
  - active request lookup
  - provider registry
  - apply provider decisions
  - HTTP API / auth / TTL store
      ↓
Provider
  - sender recognition
  - message parsing
  - OTP/code extraction
  - confirmation matching
  - action allow-list policy
```

The built-in Hax integration lives entirely in `src/moyu_tg_relay/providers/hax.py`.

## Provider contract

Implement an object with a stable lowercase `name` and an `evaluate(message, request)` method. The method receives a normalized `IncomingMessage` and the active request, and returns a `ProviderDecision`.

Supported decisions are:

- `ignore`: message is unrelated.
- `code`: attach a provider-defined one-time code to the active request.
- `click`: ask the core to execute exactly one provider-selected Telegram button.
- `human_required`: fail closed and surface a safe detail to the caller.

Providers must not directly mutate the request store. The core applies decisions so lifecycle semantics remain consistent across providers.

## Registering a provider

Add the implementation under `src/moyu_tg_relay/providers/` and register it in `build_provider_registry()`.

Example:

```python
from .base import ProviderDecision


class ExampleProvider:
    name = "example"

    def evaluate(self, message, request):
        if message.sender_username != "example_bot":
            return ProviderDecision.ignore()
        if message.text.startswith("Code: "):
            return ProviderDecision.code_ready(message.text.removeprefix("Code: ").strip())
        return ProviderDecision.ignore()
```

The HTTP caller can then create a request with:

```json
{
  "provider": "example",
  "account": "<telegram-account-id>",
  "context": {}
}
```

## Safety requirements

Provider implementations should fail closed. Automatic Telegram interaction should require explicit sender/message/action constraints and must never degrade into a generic "click Confirm" rule. Secrets and Telegram session credentials belong to the Relay deployment boundary, not provider code or configuration committed to Git.
