# Hermes Agent custom-model config reference

Authoritative for hermes-agent ≥ v0.14. Source-of-truth file:
`hermes-agent/hermes_cli/config.py` (`_normalize_custom_provider_entry`,
`get_compatible_custom_providers`, `_VALID_CUSTOM_PROVIDER_FIELDS`).

## Where things live

| File | Purpose |
|---|---|
| `~/.hermes/config.yaml` | All non-secret settings: model, providers, compression, auxiliary |
| `~/.hermes/.env` | Secrets only (`PROVIDER_API_KEY=...`). Referenced from YAML as `${VAR}` |

## Two schemas accepted side-by-side

Hermes reads both and merges via `get_compatible_custom_providers()`. They are
**equivalent at runtime** but UIs prefer different ones.

### Legacy list (what `hermes model` writes by default)

```yaml
custom_providers:
  - name: myprovider
    base_url: http://127.0.0.1:8080/v1
    api_key: ''
    api_mode: codex_responses
    model: main-model
    models:
      main-model:
        context_length: 400000
        max_output_tokens: 32000
```

### Newer dict (v12+ schema)

```yaml
providers:
  myprovider:
    name: myprovider
    base_url: http://127.0.0.1:8080/v1
    api_key: ''
    api_mode: codex_responses
    default_model: main-model
    models:
      main-model:
        context_length: 400000
        max_output_tokens: 32000
```

`providers_dict_to_custom_providers()` rewrites the dict into the list shape at
runtime; do not duplicate the same name in both sections.

## Fields per provider entry

| Field | Type | Notes |
|---|---|---|
| `name` | str | Lowercase, used as both display name and the runtime slug. Referenced as `custom:<name>`. |
| `base_url` | str | OpenAI-compatible base. Must end with `/v1` for OpenAI/Codex wire APIs. |
| `api_key` | str | Inline auth. Leave `''` for keyless local servers. Never commit a real key. |
| `key_env` | str | Name of env var in `~/.hermes/.env`. Preferred over `api_key`. Alias: `api_key_env`. |
| `api_mode` | str | `chat_completions` (most OpenAI-compatible), `codex_responses` (Codex-style Responses API), `anthropic_messages` (Anthropic-compatible proxies). Alias: `transport`. |
| `model` | str | Default model id for this provider. Alias: `default_model`. |
| `models` | dict | Per-model overrides. Keys are model ids; values must be dicts with `context_length` and `max_output_tokens`. |
| `context_length` | int | Provider-level fallback when a model is not in `models`. |
| `rate_limit_delay` | float | Optional cooldown between requests (seconds). |
| `discover_models` | bool | Whether `hermes model` may query `/v1/models` to expand the list. |

## Top-level `model:` block

```yaml
model:
  default: <model-id>           # also accepts `model:` as key name
  provider: <provider-name>     # must match custom_providers[].name
  api_mode: <api_mode>          # often duplicated from the provider entry
  max_tokens: 32000             # OUTPUT cap per response
  context_length: 400000        # optional total-window override; auto-detected if absent
  base_url: ''                  # optional override; usually empty when using custom_providers
  api_key: ''                   # optional override; prefer key_env on provider entry
```

`max_tokens` is the misnomer-but-canonical key for **output** cap. Total context
is `context_length`. See `cli-config.yaml.example` "Token limits" section.

## Compression

```yaml
compression:
  enabled: true
  threshold: 0.875              # 0 < t <= 1.0; compress once context use exceeds this fraction
  target_ratio: 0.20            # compress down to threshold * target_ratio
  protect_last_n: 20            # never compress these many most-recent messages
  hygiene_hard_message_limit: 400  # gateway safety valve by message count
```

Threshold is a fraction of the resolved context length. `0.875` triggers near
the top of the window; `0.5` (Hermes default) compresses earlier.

## Auxiliary compression model

```yaml
auxiliary:
  compression:
    provider: custom:<name>     # `custom:` prefix points at custom_providers
    model: <model-id>           # leave '' to use the main chat model
    base_url: <url>             # repeat to force the endpoint
    api_key: ''
    api_mode: <api_mode>
    context_length: <int>       # must be >= main model context window
    timeout: 120
    extra_body: {}
```

Constraint: the summary model's context window **must be ≥** the main model's,
or middle-of-conversation turns are silently dropped when compression fails.

## Provider resolution chain

`runtime_provider.resolve_provider_full(name, user_providers, custom_providers)`:

1. Built-in providers (the named aliases Hermes ships with — see
   `cli-config.yaml.example` in the hermes-agent repo for the current list).
2. `providers:` dict from config.
3. `custom_providers:` list from config (legacy).
4. URL-based fallback: `base_url` with `provider: custom` and no name resolves
   against the credential pool.

The first match wins. A `custom_providers` entry whose `name` collides with one
of those built-in aliases overrides the alias.

## `api_mode` selection

| Endpoint behavior | `api_mode` |
|---|---|
| OpenAI-style `/v1/chat/completions` (default) | `chat_completions` |
| OpenAI Codex-style `/v1/responses` | `codex_responses` |
| Anthropic-compatible `/v1/messages` proxy | `anthropic_messages` |

Wrong `api_mode` typically surfaces as empty `tool_calls.arguments` or 400 errors
on the first tool-using turn. Set it explicitly; auto-detection from URL is only
a fallback.

## Validation

`hermes config check` validates env-var presence. `hermes doctor` validates the
broader environment (network, paths, optional advisories). Neither verifies the
provider responds, so always sanity-check the endpoint with
`curl -sS <base_url>/models` after merging.
