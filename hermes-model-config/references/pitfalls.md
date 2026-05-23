# Hermes custom-model pitfalls (battle-tested)

Distilled from real Hermes setups, including `hermes-model-config-export-notes.md`
on machines that have run this configuration end-to-end.

## 1. Wrong `api_mode` silently breaks tool calls

`codex_responses` and `chat_completions` are not interchangeable. A
Responses/Codex-style server pointed at via `chat_completions` will return data
where
`tool_calls.arguments` is empty (no JSON), and Hermes spins on retries.
Endpoints that speak the Codex-style Responses API must use `codex_responses`.
Plain OpenAI-compatible chat endpoints use `chat_completions`.
Anthropic-Messages-compatible proxies use `anthropic_messages`.

Do not write `api_mode: responses` in YAML. `responses` is accepted as an
interactive picker alias and is normalized to `codex_responses`; config files
must use `codex_responses`.

Set `api_mode` explicitly on both the `model:` block and the `custom_providers`
entry — do not rely on URL auto-detection.

## 2. Running sessions do not pick up the new config

Editing `~/.hermes/config.yaml` only affects **new sessions**. Existing chat
sessions (including the Telegram/Discord gateways) keep the agent they were
constructed with. To take effect:

- `hermes gateway restart` for messaging gateways.
- `/new` or restart the CLI for interactive sessions.
- Inside an existing session you can hot-switch with
  `/model <model> --provider <name>` (uses the new entry without restart).

Exception: changing `compression.*` or `model.context_length` on a running
gateway *is* hot-reloaded on the next message (config version ≥ 17). Other keys
are not.

## 3. `model.default` ≠ current chat session

The saved global default is what new sessions start with. Existing sessions and
the gateway can be on a different model. When exporting/migrating, decide
explicitly whether you want the current session's model or the saved default.

## 4. Internal-IP `base_url` does not travel

`http://192.168.x.y:8080/v1` is only reachable from the same LAN. Before
copying a config to another host:

- Either expose the endpoint via a public reverse proxy.
- Or rewrite `base_url` to the public URL of that proxy.
- Or run an SSH tunnel and point `base_url` at `http://127.0.0.1:<localport>/v1`.

## 5. Never duplicate entries in `custom_providers`

Older configs accumulate multiple entries with the same `name` from repeated
`hermes model` runs. `get_compatible_custom_providers()` deduplicates by
`(name, base_url, model)` but UIs may show duplicates and the picker becomes
confusing. Keep exactly one entry per logical provider; delete stale duplicates
before committing.

## 6. Context length must be an integer

`context_length: 400K` and `context_length: "400000"` both make Hermes reject
the override and fall back to auto-detection. Always write a bare int:
`context_length: 400000`.

## 7. Secrets do not belong in `config.yaml`

`config.yaml` is checked into backups, exported to migration files, and shown
by `hermes config show`. Real API keys go in `~/.hermes/.env`:

```
PROVIDER_API_KEY=sk-...
```

Then in YAML use `key_env: PROVIDER_API_KEY` (preferred) or
`api_key: ${PROVIDER_API_KEY}` (legacy substitution).

## 8. `provider` naming must align

The string used in `model.provider` and the one used in `custom_providers[].name`
must match exactly. The auxiliary compression model adds a `custom:` prefix when
referencing a custom provider — so `model.provider: myprovider` pairs with
`auxiliary.compression.provider: custom:myprovider`. A mismatch silently routes
the compression call to the auto-detect chain (often the main provider works,
but a misnamed custom provider returns "provider not found" warnings in logs).

## 9. Summary model context must be ≥ main model context

The compressor sends the full middle window to the summary model. If you point
`auxiliary.compression` at a smaller-context model, the call fails and the
middle is dropped silently — the conversation loses context without any
user-visible error. Match or exceed the main model's `context_length`.

## 10. Picker hides providers via `model_picker.hidden_providers`

If your new provider does not show up in `/model`, check
`model_picker.hidden_providers` in `config.yaml` — providers listed there are
suppressed from the picker even if they're declared elsewhere. Remove your
provider's name from that list if it was suppressed earlier.

## 11. `custom_providers:` must be a YAML list, not a dict

Older hand-written configs sometimes drop the `-` prefix and produce a dict.
`runtime_provider.py` logs:

> custom_providers in config.yaml is a dict, not a list. Each entry must be
> prefixed with '-' in YAML. Run 'hermes doctor' for details.

…and then ignores the entry. Either keep the list shape or migrate to the
newer `providers:` dict shape (under `providers:`, each entry **is** a dict
keyed by name).

## 12. `auxiliary.compression.base_url` overrides `provider`

If both are set, the base_url wins. Use this to force a specific endpoint when
the provider auto-resolution would pick the wrong route (e.g. when two custom
providers share a name across overlay layers).
