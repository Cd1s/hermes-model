---
name: hermes-model-config
description: Use when configuring a Hermes Agent custom model from user-supplied api_key/base_url/api_mode/model/context_length/max_output_tokens/compression settings. Merges a single custom_providers entry plus top-level model defaults, compression threshold, and auxiliary.compression into ~/.hermes/config.yaml without clobbering other sections, with backup-merge-validate-restore steps.
version: 1.0.0
author: Cd1s
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [hermes-agent, model, custom-provider, config, yaml, compression, auxiliary]
    related_skills: [hermes-agent-skill-authoring]
---

# Hermes Agent custom-model configuration

## Overview

When the user hands over the parameters for a new Hermes inference endpoint
(API key / endpoint URL / wire protocol / model id / context / output cap /
compression knobs), this skill turns those into a correctly-shaped delta on
`~/.hermes/config.yaml`. It targets the **legacy `custom_providers:` list
schema** that `hermes_cli/config.py::get_compatible_custom_providers` reads at
runtime and that `hermes model` writes by default. The newer dict-keyed
`providers:` schema is read-compatible, but the merge tooling here writes the
list form because it round-trips losslessly with every Hermes version since
v0.10.

Outputs:

1. A normalized entry in `custom_providers:` (insert or replace by `name`).
2. Optional updates to top-level `model.default` / `model.provider` /
   `model.api_mode` / `model.max_tokens` / `model.context_length`.
3. Optional `compression.threshold` update.
4. Optional `auxiliary.compression.{provider, model, base_url, api_mode,
   context_length, timeout}` update — supports `provider: custom:<name>` to
   point compression at this same custom provider.

Every write is preceded by a timestamped backup of `config.yaml` and (when the
operator opts into a live test) `.env`. Other sections — telegram, gateway,
terminal, browser, cron, skills, kanban — are preserved untouched.

## When to Use

- The user pastes/dictates a provider's `api_key`, `base_url`, `api_mode`,
  default model, context window, output cap, etc., and asks to "set up the
  model" / "配置自定义模型" / "merge this into Hermes config".
- The user is migrating a model entry from another machine (`hermes-model-config-export.yaml`
  shape) and wants it merged, not overwritten.
- The user wants to adjust compression: change the threshold, repoint
  `auxiliary.compression` at a cheaper/faster model, or set its endpoint.
- The user wants a no-op live test — drop a placeholder provider in, confirm
  Hermes still parses the config, then restore exactly.

**Don't use this skill for:** providers already built into Hermes — those are
configured via `hermes model` + env vars and do not need a `custom_providers`
entry. For those, point the user at `hermes model`.

## Inputs to collect from the user

Required (refuse to proceed without):

| Field | CLI flag | Notes |
|---|---|---|
| Provider name | `--provider-name` | Lowercase, underscores or hyphens, no spaces. This is the runtime slug — `model.provider: <name>` and `auxiliary.compression.provider: custom:<name>` must reference it exactly. |
| Endpoint base URL | `--base-url` | OpenAI-compatible base, must include `/v1` for OpenAI/Codex wire APIs. |
| Wire protocol | `--api-mode` | One of `chat_completions`, `codex_responses`, `anthropic_messages` (also accepted by this script: `bedrock_converse`). Use `codex_responses` for `/v1/responses`; do not write `responses` in config. |
| Default model id | `--default-model` | Must match one of the `--model` entries below; auto-added with placeholder values if missing. |
| At least one model | `--model id:context_length:max_output_tokens` | Repeatable. Both integers must be positive; never write `400K` style strings. |
| Auth | `--api-key ''` OR `--key-env VARNAME` | Mutually exclusive. Use empty `api_key` for keyless local servers; use `key_env` for hosted endpoints (then place the secret in `~/.hermes/.env`). |

Optional:

| Field | CLI flag | Notes |
|---|---|---|
| Set as new default | `--set-default` | Updates `model.default` / `model.provider` / `model.api_mode`. |
| Output cap (top-level) | `--max-tokens INT` | Sets `model.max_tokens` (only with `--set-default`). |
| Override total context | `--top-context-length INT` | Sets `model.context_length`. Usually leave unset — Hermes auto-detects. |
| Compression threshold | `--compression-threshold 0.875` | Range `(0, 1.0]`. |
| Compression provider | `--compression-provider custom:<name>` | For a cheap/fast compression model on the same custom endpoint. |
| Compression model | `--compression-model <id>` | Empty/unset means "use main model". |
| Compression endpoint | `--compression-base-url`, `--compression-api-key`, `--compression-api-mode`, `--compression-context-length`, `--compression-timeout` | Use when compression talks to a different server than the main model. |
| Provider-level fallback context | `--provider-context-length INT` | For providers where the per-model dict is sparse. |
| Rate-limit pacing | `--rate-limit-delay SECONDS` | Cooldown between requests on rate-limited providers. |

If any required value is missing or ambiguous, ask **once**, then proceed.

### `api_mode` quick rule

Hermes defaults unknown/custom endpoints to `chat_completions` unless URL
heuristics detect a special endpoint. For custom providers, set `api_mode`
explicitly:

- `/v1/chat/completions` or ordinary OpenAI-compatible chat server:
  `chat_completions`
- `/v1/responses` / Responses API / Codex-compatible tool-calling backend:
  `codex_responses`
- Anthropic Messages-compatible endpoint: `anthropic_messages`

`responses` is accepted by Hermes' interactive picker as a user input alias,
but it is **not** a valid `config.yaml` value. Persist `codex_responses`.

## Workflow

The skill ships three scripts. They are deliberately self-contained — runnable
from any clone of this repo with Python 3.9+ and PyYAML (or ideally
`ruamel.yaml` for comment-preserving round-trips).

### Step 1: Back up

Always back up before merging. `backup_restore.sh` writes a tagged snapshot
under `~/.hermes/backups/hermes-model-config/<tag>/`:

```bash
bash scripts/backup_restore.sh backup        # autogenerates timestamp tag
# or
bash scripts/backup_restore.sh backup mytag
```

Both `config.yaml` and `.env` are copied (with permissions preserved) plus a
`sha256sum.txt` for later integrity checks.

### Step 2: Merge

```bash
python3 scripts/merge_config.py \
    --config ~/.hermes/config.yaml \
    --provider-name myprovider \
    --base-url http://127.0.0.1:8080/v1 \
    --api-mode codex_responses \
    --default-model main-model \
    --model main-model:400000:32000 \
    --model compress-model:400000:32000 \
    --api-key '' \
    --set-default --max-tokens 32000 \
    --compression-threshold 0.875 \
    --compression-provider custom:myprovider \
    --compression-model compress-model \
    --compression-base-url http://127.0.0.1:8080/v1 \
    --compression-api-mode codex_responses \
    --compression-context-length 400000
```

Behavior:
- Writes a fresh backup as `<config>.bak_hermes_model_config_<ts>` next to the
  config (independent of step 1's backup).
- Inserts or **replaces** the matching `custom_providers` entry by `name` —
  never appends duplicates.
- Preserves every other top-level section verbatim (uses `ruamel.yaml`
  round-trip when available).
- `--dry-run` prints the merged YAML to stdout instead of writing.

For a hosted provider (key in `.env`):

```bash
python3 scripts/merge_config.py \
    --config ~/.hermes/config.yaml \
    --provider-name hostedprovider \
    --base-url https://api.example.com/v1 \
    --api-mode chat_completions \
    --default-model fast-model \
    --model fast-model:200000:64000 \
    --key-env HOSTEDPROVIDER_API_KEY
```

Then make sure `~/.hermes/.env` contains `HOSTEDPROVIDER_API_KEY=...`.

### Step 3: Validate

`hermes config check` only validates env-var presence. To validate the
**schema** of the merged config:

```bash
python3 scripts/validate_config.py --config ~/.hermes/config.yaml
```

Hard errors (non-zero exit): bad list/dict shape, bad `api_mode`, non-int
`context_length` / `max_output_tokens`, `compression.threshold` out of range,
`auxiliary.compression.provider: custom:<x>` referencing undeclared `<x>`.

Warnings (still exits zero): missing `api_mode`, missing auth on a hosted
provider, default model not listed in `models`, compression context smaller
than main context, duplicated provider names across `providers:` and
`custom_providers:`.

Then run the built-in checks:

```bash
hermes config check
hermes doctor
```

`hermes doctor` may print unrelated advisories — only investigate ones touching
`model`, `providers`, or `compression`.

### Step 4: Sanity-check the endpoint

```bash
curl -sS "<base_url>/models" | head
```

If this fails, the merge is correct on paper but the endpoint is unreachable.
Do not blame Hermes — fix networking first (internal IP, VPN, proxy, etc.).

### Step 5 (test-only): Restore

For dry-run validation or live tests on the operator's own machine:

```bash
bash scripts/backup_restore.sh restore <tag>
bash scripts/backup_restore.sh verify  <tag>
```

`verify` is `cmp -s` between the restored file and the backup tag — it returns
exit 3 with a diff if anything drifted.

## Canonical YAML shape

The fragment this skill emits (see `templates/custom_provider.yaml`):

```yaml
model:
  default: main-model
  provider: myprovider
  api_mode: codex_responses
  max_tokens: 32000
  # context_length: 400000   # optional override

custom_providers:
  - name: myprovider
    base_url: http://127.0.0.1:8080/v1
    api_key: ''                    # or: key_env: MYPROVIDER_API_KEY
    api_mode: codex_responses
    model: main-model
    models:
      main-model:
        context_length: 400000
        max_output_tokens: 32000
      compress-model:
        context_length: 400000
        max_output_tokens: 32000

compression:
  enabled: true
  threshold: 0.875

auxiliary:
  compression:
    provider: custom:myprovider
    model: compress-model
    base_url: http://127.0.0.1:8080/v1
    api_key: ''
    api_mode: codex_responses
    context_length: 400000
    timeout: 120
    extra_body: {}
```

Full schema reference: `references/schema.md`. Pitfall catalog:
`references/pitfalls.md`.

## Common Pitfalls

1. **Confusing `model.default` (saved default) with the running session's
   model.** Editing config does not change sessions already in progress. Tell
   the user to `/new` or use `/model <id> --provider <name>` mid-session.

2. **Forgetting to set `api_mode`.** URL-based detection is a fallback, not a
   guarantee. Always set `api_mode` explicitly. A Responses/Codex-style endpoint
   hit with `chat_completions` returns empty `tool_calls.arguments` and Hermes
   will spin. The value to write is `codex_responses`, not `responses`.

3. **Committing the API key into `config.yaml`.** Use `key_env: VARNAME` and put
   the secret in `~/.hermes/.env`. Never run `merge_config.py` with
   `--api-key sk-...` on a shared box.

4. **Writing `context_length: "400000"` or `400K`.** Both fail Hermes' int
   check and silently fall back to auto-detection. Always a bare integer.

5. **Letting `custom_providers` accumulate duplicates.** `merge_config.py`
   updates the entry in-place keyed by `name`, but old hand-edited duplicates
   may already exist — run `validate_config.py` to surface them.

6. **Compression context smaller than main context.** Causes the summary call
   to fail and middle turns to drop silently. The validator emits a warning.

7. **Pointing `auxiliary.compression.provider` at a custom provider without
   the `custom:` prefix.** Bare `provider: myprovider` does not resolve;
   needs `provider: custom:myprovider`.

8. **Treating internal LAN base_urls as portable.** A `192.168.x.y` endpoint
   that works on the source machine will time out on a different network.
   Replace with the public reverse-proxy URL before exporting.

9. **Running `merge_config.py` with `--no-backup` outside CI.** That flag exists
   for ephemeral pipelines only. On any real machine, always take a backup
   first.

10. **Forgetting to restart the gateway.** `compression.*` and
    `model.context_length` hot-reload; everything else under `model:` /
    `custom_providers:` only applies to new sessions. `hermes gateway restart`
    if Telegram/Discord/Slack gateways are running.

## Verification Checklist

- [ ] `~/.hermes/backups/hermes-model-config/<tag>/{config.yaml,.env}` exists
      before any merge.
- [ ] `python3 scripts/merge_config.py ... --dry-run` previewed the result and
      the user OK'd it (skip only when running unattended in a script).
- [ ] After merge: `python3 scripts/validate_config.py --config ~/.hermes/config.yaml`
      exits 0.
- [ ] `hermes config check` exits 0; no missing required env vars.
- [ ] `hermes doctor` exits 0 or only emits unrelated advisories.
- [ ] `curl -sS <base_url>/models` returns JSON listing the configured model
      (run from the box where Hermes will actually run).
- [ ] If the merge was for testing only: `backup_restore.sh restore <tag>`
      followed by `backup_restore.sh verify <tag>` reports MATCH for both
      `config.yaml` and `.env`.
- [ ] Gateways restarted if they were running before the merge.

## One-shot recipes

### Add a hosted provider with key in `.env`

```bash
bash scripts/backup_restore.sh backup hosted-example
python3 scripts/merge_config.py \
    --provider-name hostedprovider \
    --base-url https://api.example.com/v1 \
    --api-mode chat_completions \
    --default-model fast-model \
    --model fast-model:1000000:384000 \
    --model pro-model:1000000:384000 \
    --key-env HOSTEDPROVIDER_API_KEY \
    --provider-context-length 1000000
python3 scripts/validate_config.py
hermes config check
```

### Drop a placeholder provider for a config-merge test, then roll back

```bash
bash scripts/backup_restore.sh backup test-noop
python3 scripts/merge_config.py \
    --provider-name testskill_demo \
    --base-url https://example.invalid/v1 \
    --api-mode chat_completions \
    --default-model demo-model \
    --model demo-model:8192:2048 \
    --api-key ''
python3 scripts/validate_config.py
hermes config check
bash scripts/backup_restore.sh restore test-noop
bash scripts/backup_restore.sh verify  test-noop
```

### Switch the saved default model to a new provider

```bash
bash scripts/backup_restore.sh backup
python3 scripts/merge_config.py \
    --provider-name myprovider \
    --base-url http://127.0.0.1:8080/v1 \
    --api-mode codex_responses \
    --default-model main-model \
    --model main-model:400000:32000 \
    --api-key '' \
    --set-default --max-tokens 32000
hermes gateway restart   # only if a gateway is running
```
