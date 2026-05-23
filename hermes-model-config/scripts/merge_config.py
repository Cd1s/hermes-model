#!/usr/bin/env python3
"""Merge a Hermes Agent custom-provider fragment into ~/.hermes/config.yaml.

Designed to be invoked by the `hermes-model-config` skill once it has gathered
the user's provider parameters. Writes a timestamped backup of the target
config before any modification.

Round-trips with ruamel.yaml when available (preserves user comments and
ordering). Falls back to PyYAML if ruamel.yaml is not installed; PyYAML loses
comments on save, so the script prints a warning in that case.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from ruamel.yaml import YAML  # type: ignore
    _USE_RUAMEL = True
except ImportError:  # pragma: no cover - exercised on machines without ruamel
    _USE_RUAMEL = False
    import yaml  # type: ignore

VALID_API_MODES = {
    "chat_completions",
    "codex_responses",
    "anthropic_messages",
    "bedrock_converse",
}

API_MODE_ALIASES = {
    "responses": "codex_responses",
    "codex": "codex_responses",
    "completions": "chat_completions",
    "chat": "chat_completions",
    "messages": "anthropic_messages",
    "anthropic": "anthropic_messages",
}


def _api_mode_arg(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in VALID_API_MODES:
        return normalized
    if normalized in API_MODE_ALIASES:
        canonical = API_MODE_ALIASES[normalized]
        raise argparse.ArgumentTypeError(
            f"{value!r} is an interactive alias, not a config value; use {canonical!r}"
        )
    raise argparse.ArgumentTypeError(
        f"invalid api_mode {value!r}; expected one of {sorted(VALID_API_MODES)}"
    )


def _optional_api_mode_arg(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return ""
    return _api_mode_arg(value)


def _load_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return {}
    if _USE_RUAMEL:
        y = YAML()
        y.preserve_quotes = True
        return y.load(text) or {}
    return yaml.safe_load(text) or {}


def _dump_yaml(data: Dict[str, Any], path: Path) -> None:
    if _USE_RUAMEL:
        y = YAML()
        y.preserve_quotes = True
        y.width = 4096
        y.indent(mapping=2, sequence=2, offset=0)
        with path.open("w", encoding="utf-8") as fh:
            y.dump(data, fh)
        return
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True)


def _dump_yaml_str(data: Dict[str, Any]) -> str:
    if _USE_RUAMEL:
        from io import StringIO

        y = YAML()
        y.preserve_quotes = True
        y.width = 4096
        y.indent(mapping=2, sequence=2, offset=0)
        buf = StringIO()
        y.dump(data, buf)
        return buf.getvalue()
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def parse_model_spec(spec: str) -> Tuple[str, int, int]:
    """Parse a "model_id:context:output" CLI arg.

    Examples:
        main-model:400000:32000
        compact-model:128000:16384
    """
    parts = spec.split(":")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError(
            f"--model expects 'id:context_length:max_output_tokens', got {spec!r}"
        )
    model_id, ctx, out = parts[0].strip(), parts[1].strip(), parts[2].strip()
    if not model_id:
        raise argparse.ArgumentTypeError("model id must not be empty")
    try:
        ctx_i = int(ctx)
        out_i = int(out)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"context_length and max_output_tokens must be integers (got {ctx!r}, {out!r})"
        ) from exc
    if ctx_i <= 0 or out_i <= 0:
        raise argparse.ArgumentTypeError("context_length and max_output_tokens must be positive")
    return model_id, ctx_i, out_i


def _normalize_models(model_specs: List[Tuple[str, int, int]]) -> Dict[str, Dict[str, int]]:
    out: Dict[str, Dict[str, int]] = {}
    for mid, ctx, mx in model_specs:
        out[mid] = {"context_length": ctx, "max_output_tokens": mx}
    return out


def _ensure_list(node: Any) -> List[Any]:
    if node is None:
        return []
    if isinstance(node, list):
        return node
    return []


def _upsert_custom_provider(
    config: Dict[str, Any],
    provider_entry: Dict[str, Any],
) -> str:
    """Insert or replace the matching entry under custom_providers. Returns 'inserted' or 'updated'."""
    name = provider_entry["name"]
    raw = config.get("custom_providers")
    if raw is None:
        config["custom_providers"] = [provider_entry]
        return "inserted"
    if not isinstance(raw, list):
        raise SystemExit(
            "custom_providers in target config is not a list. "
            "This script only supports the list shape; convert manually before merging."
        )
    for idx, entry in enumerate(raw):
        if not isinstance(entry, dict):
            continue
        if str(entry.get("name", "")).strip().lower() == name.lower():
            raw[idx] = provider_entry
            return "updated"
    raw.append(provider_entry)
    return "inserted"


def _set_path(config: Dict[str, Any], dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    cur: Any = config
    for p in parts[:-1]:
        if p not in cur or not isinstance(cur[p], dict):
            cur[p] = {}
        cur = cur[p]
    cur[parts[-1]] = value


def build_provider_entry(args: argparse.Namespace, models_dict: Dict[str, Dict[str, int]]) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "name": args.provider_name,
        "base_url": args.base_url,
        "api_mode": args.api_mode,
        "model": args.default_model,
        "models": models_dict,
    }
    if args.key_env:
        entry["key_env"] = args.key_env
        # api_key intentionally left absent — runtime falls back to env var
    else:
        # Inline empty string is the documented form for keyless local servers.
        entry["api_key"] = args.api_key if args.api_key is not None else ""
    if args.provider_context_length is not None:
        entry["context_length"] = args.provider_context_length
    if args.rate_limit_delay is not None:
        entry["rate_limit_delay"] = args.rate_limit_delay
    return entry


def make_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Merge a Hermes custom-model provider into ~/.hermes/config.yaml.",
    )
    p.add_argument("--config", default=os.path.expanduser("~/.hermes/config.yaml"))
    p.add_argument("--backup-dir", default=None,
                   help="Directory for backups. Defaults to alongside --config.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print merged YAML to stdout; do not write or back up.")
    p.add_argument("--no-backup", action="store_true",
                   help="Skip backup (dangerous; only for ephemeral CI).")

    p.add_argument("--provider-name", required=True,
                   help="custom_providers[].name; lowercase identifier.")
    p.add_argument("--base-url", required=True)
    p.add_argument("--api-mode", required=True, type=_api_mode_arg)
    p.add_argument("--default-model", required=True,
                   help="Model id used when this provider is selected without an explicit model.")
    p.add_argument("--model", dest="model_specs", action="append", type=parse_model_spec,
                   default=[], required=True,
                   metavar="MODEL_ID:CONTEXT:MAX_OUTPUT",
                   help="Repeatable. At least one. Example: main-model:400000:32000")

    auth = p.add_mutually_exclusive_group(required=True)
    auth.add_argument("--api-key", default=None,
                      help="Inline api_key. Use '' for keyless local servers.")
    auth.add_argument("--key-env", default=None,
                      help="Env var name in ~/.hermes/.env (preferred for hosted providers).")

    p.add_argument("--provider-context-length", type=int, default=None,
                   help="Optional provider-level fallback context_length.")
    p.add_argument("--rate-limit-delay", type=float, default=None)

    p.add_argument("--set-default", action="store_true",
                   help="Also set top-level model.default/provider/api_mode to this provider.")
    p.add_argument("--max-tokens", type=int, default=None,
                   help="Top-level model.max_tokens (output cap). Only used with --set-default.")
    p.add_argument("--top-context-length", type=int, default=None,
                   help="Top-level model.context_length override. Only used with --set-default.")

    p.add_argument("--compression-threshold", type=float, default=None,
                   help="Set compression.threshold (0 < t <= 1.0).")
    p.add_argument("--compression-provider", default=None,
                   help="auxiliary.compression.provider. Use 'custom:<name>' for a custom provider.")
    p.add_argument("--compression-model", default=None)
    p.add_argument("--compression-base-url", default=None)
    p.add_argument("--compression-api-key", default=None)
    p.add_argument("--compression-api-mode", default=None, type=_optional_api_mode_arg)
    p.add_argument("--compression-context-length", type=int, default=None)
    p.add_argument("--compression-timeout", type=int, default=None)

    return p


def _backup(config_path: Path, backup_dir: Optional[Path]) -> Path:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    dest_dir = backup_dir or config_path.parent
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{config_path.name}.bak_hermes_model_config_{stamp}"
    shutil.copy2(config_path, dest)
    return dest


def merge(args: argparse.Namespace) -> int:
    if args.compression_threshold is not None:
        if not (0 < args.compression_threshold <= 1.0):
            print("compression-threshold must be in (0, 1.0]", file=sys.stderr)
            return 2

    config_path = Path(args.config)
    config = _load_yaml(config_path) if config_path.exists() else {}
    if not isinstance(config, dict):
        print(f"{config_path} is not a YAML mapping; refusing to merge.", file=sys.stderr)
        return 2

    models_dict = _normalize_models(args.model_specs)
    if args.default_model not in models_dict:
        print(
            f"Warning: --default-model {args.default_model!r} is not declared in --model "
            f"entries. Adding a placeholder with context=131072 / output=8192. "
            f"Re-run with an explicit --model {args.default_model}:CTX:OUT if those values are wrong.",
            file=sys.stderr,
        )
        models_dict[args.default_model] = {
            "context_length": 131072,
            "max_output_tokens": 8192,
        }

    entry = build_provider_entry(args, models_dict)
    action = _upsert_custom_provider(config, entry)

    if args.set_default:
        _set_path(config, "model.default", args.default_model)
        _set_path(config, "model.provider", args.provider_name)
        _set_path(config, "model.api_mode", args.api_mode)
        if args.max_tokens is not None:
            _set_path(config, "model.max_tokens", args.max_tokens)
        if args.top_context_length is not None:
            _set_path(config, "model.context_length", args.top_context_length)

    if args.compression_threshold is not None:
        _set_path(config, "compression.enabled", True)
        _set_path(config, "compression.threshold", args.compression_threshold)

    if any(
        v is not None
        for v in (
            args.compression_provider,
            args.compression_model,
            args.compression_base_url,
            args.compression_api_key,
            args.compression_api_mode,
            args.compression_context_length,
            args.compression_timeout,
        )
    ):
        if args.compression_provider is not None:
            _set_path(config, "auxiliary.compression.provider", args.compression_provider)
        if args.compression_model is not None:
            _set_path(config, "auxiliary.compression.model", args.compression_model)
        if args.compression_base_url is not None:
            _set_path(config, "auxiliary.compression.base_url", args.compression_base_url)
        if args.compression_api_key is not None:
            _set_path(config, "auxiliary.compression.api_key", args.compression_api_key)
        if args.compression_api_mode is not None:
            _set_path(config, "auxiliary.compression.api_mode", args.compression_api_mode)
        if args.compression_context_length is not None:
            _set_path(config, "auxiliary.compression.context_length", args.compression_context_length)
        if args.compression_timeout is not None:
            _set_path(config, "auxiliary.compression.timeout", args.compression_timeout)

    if args.dry_run:
        sys.stdout.write(_dump_yaml_str(config))
        print(
            f"\n# dry-run: provider {entry['name']!r} would be {action}; no files written.",
            file=sys.stderr,
        )
        return 0

    backup_path: Optional[Path] = None
    if config_path.exists() and not args.no_backup:
        backup_path = _backup(
            config_path,
            Path(args.backup_dir) if args.backup_dir else None,
        )

    config_path.parent.mkdir(parents=True, exist_ok=True)
    _dump_yaml(config, config_path)

    if not _USE_RUAMEL:
        print(
            "Note: ruamel.yaml not installed; the rewritten file is functionally "
            "equivalent but loses comments and key order. Install ruamel.yaml "
            "for round-trip-preserving merges.",
            file=sys.stderr,
        )

    print(f"Merged custom_provider entry ({action}): {entry['name']}")
    print(f"  base_url:       {entry['base_url']}")
    print(f"  api_mode:       {entry['api_mode']}")
    print(f"  default model:  {entry['model']}")
    print(f"  models:         {', '.join(models_dict.keys())}")
    if args.set_default:
        print(f"  top-level model.default set to: {args.default_model}")
    if backup_path is not None:
        print(f"Backup written to: {backup_path}")
    print(
        "Next: run `python3 scripts/validate_config.py "
        f"--config {config_path}` to sanity-check structure, "
        "then `hermes config check` and `hermes doctor`."
    )
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = make_argparser().parse_args(argv)
    return merge(args)


if __name__ == "__main__":
    sys.exit(main())
