# Hermes Model Skills

This repository contains Hermes Agent skills for configuring model providers.

## Included Skill

### `hermes-model-config`

Use this skill when configuring a Hermes Agent custom model from user-provided
values such as:

- provider name
- `base_url`
- `api_key` or `key_env`
- `api_mode`
- model id
- context length
- max output tokens
- compression threshold
- auxiliary compression provider/model

The skill includes deterministic helper scripts for merging into
`~/.hermes/config.yaml`, validating the YAML shape, backing up local config, and
restoring after live tests.

## Install On Another Machine

Clone the repository:

```bash
git clone https://github.com/Cd1s/hermes-model.git
cd hermes-model
```

Install the skill into the local Hermes skills directory:

```bash
mkdir -p ~/.hermes/skills
cp -a hermes-model-config ~/.hermes/skills/hermes-model-config
```

For development, use a symlink instead of copying:

```bash
mkdir -p ~/.hermes/skills
ln -sfn "$(pwd)/hermes-model-config" ~/.hermes/skills/hermes-model-config
```

## Verify Installation

Check that the skill file exists:

```bash
test -f ~/.hermes/skills/hermes-model-config/SKILL.md
```

Validate the helper scripts:

```bash
python3 ~/.hermes/skills/hermes-model-config/scripts/validate_config.py --config ~/.hermes/config.yaml
bash -n ~/.hermes/skills/hermes-model-config/scripts/backup_restore.sh
```

If Hermes Agent is already running, start a new session so the skills list is
reloaded.

## Usage Prompt

After installation, ask Hermes Agent something like:

```text
Use the hermes-model-config skill to add a custom model provider.
provider name: myprovider
base_url: https://api.example.com/v1
api_mode: chat_completions
default model: main-model
model: main-model:200000:64000
auth: key_env MYPROVIDER_API_KEY
compression threshold: 0.875
```

Put real API keys in `~/.hermes/.env`, not in `config.yaml`:

```bash
printf '%s\n' 'MYPROVIDER_API_KEY=replace-with-real-key' >> ~/.hermes/.env
```

## Manual Script Usage

The skill can also be used directly from this repository:

```bash
cd hermes-model/hermes-model-config
bash scripts/backup_restore.sh backup before-model-change
python3 scripts/merge_config.py \
  --provider-name myprovider \
  --base-url https://api.example.com/v1 \
  --api-mode chat_completions \
  --default-model main-model \
  --model main-model:200000:64000 \
  --key-env MYPROVIDER_API_KEY \
  --set-default \
  --max-tokens 64000
python3 scripts/validate_config.py --config ~/.hermes/config.yaml
hermes config check
```

Rollback if needed:

```bash
bash scripts/backup_restore.sh restore before-model-change
bash scripts/backup_restore.sh verify before-model-change
```

## Safety Notes

- Do not commit real API keys, tokens, auth files, state databases, sessions, or
  local backups.
- `merge_config.py` inserts or replaces one `custom_providers` entry by name; it
  does not overwrite the whole Hermes config.
- Use `key_env` for hosted providers and store the secret in `~/.hermes/.env`.
- Existing Hermes sessions may need `/new` or a gateway restart before model
  changes are used.
