#!/usr/bin/env python3
"""Validate a Hermes Agent config.yaml for custom-model correctness.

Checks the subset of fields this skill writes:
  - custom_providers / providers schema
  - model.* defaults reference a known provider
  - compression.threshold range
  - auxiliary.compression provider/model/base_url consistency
  - integer typing for context_length / max_output_tokens

Exits non-zero with a summary if any hard error is found. Warnings (non-blocking)
print to stderr but do not affect the exit code.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    from ruamel.yaml import YAML  # type: ignore
    _USE_RUAMEL = True
except ImportError:
    _USE_RUAMEL = False
    import yaml  # type: ignore

VALID_API_MODES = {
    "chat_completions",
    "codex_responses",
    "anthropic_messages",
    "bedrock_converse",
    "codex_app_server",
    "",
}

API_MODE_ALIASES = {
    "responses": "codex_responses",
    "codex": "codex_responses",
    "completions": "chat_completions",
    "chat": "chat_completions",
    "messages": "anthropic_messages",
    "anthropic": "anthropic_messages",
}


def _validate_api_mode_value(
    value: Any,
    location: str,
    errors: List[str],
) -> None:
    mode = str(value or "").strip().lower()
    if mode in VALID_API_MODES:
        return
    canonical = API_MODE_ALIASES.get(mode.strip().lower())
    if canonical:
        errors.append(
            f"{location} invalid: {value!r}; use {canonical!r} in config.yaml "
            "(`responses`/`codex` are interactive picker aliases only)"
        )
        return
    errors.append(
        f"{location} invalid: {value!r}; expected one of {sorted(VALID_API_MODES - {''})}"
    )

# Hermes ships a set of built-in provider aliases (the named providers
# selectable via `hermes model`). Discover them at runtime so this validator
# does not need to enumerate vendor names. When the Hermes install is not
# importable, return None and skip built-in-alias warnings rather than emitting
# false positives for valid local installs.
def _load_builtin_providers() -> Optional[Set[str]]:
    base = {"auto", "custom"}
    try:
        from hermes_cli import providers as _hp  # type: ignore
    except Exception:
        return None
    candidates: Set[str] = set()
    for attr in ("BUILTIN_PROVIDERS", "PROVIDER_ALIASES", "PROVIDERS"):
        v = getattr(_hp, attr, None)
        if isinstance(v, dict):
            for k in v.keys():
                if isinstance(k, str):
                    candidates.add(k.lower())
        elif isinstance(v, (set, list, tuple)):
            for k in v:
                if isinstance(k, str):
                    candidates.add(k.lower())
    return base | candidates


BUILTIN_PROVIDERS = _load_builtin_providers()


def _entry_value(entry: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key not in entry:
            continue
        value = entry.get(key)
        if isinstance(value, str):
            if value.strip():
                return value
            continue
        if value is not None:
            return value
    return None


def _entry_has_auth(entry: Dict[str, Any]) -> bool:
    for key in ("api_key", "apiKey"):
        if key in entry and entry.get(key) is not None:
            return True
    for key in ("key_env", "keyEnv", "api_key_env", "apiKeyEnv"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return True
    return False


def _load_yaml(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if _USE_RUAMEL:
        y = YAML(typ="safe")
        return y.load(text) or {}
    return yaml.safe_load(text) or {}


def _collect_custom_provider_names(config: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    out: List[Tuple[str, Dict[str, Any]]] = []
    cps = config.get("custom_providers")
    if isinstance(cps, list):
        for entry in cps:
            if isinstance(entry, dict):
                name = str(entry.get("name", "")).strip()
                if name:
                    out.append((name, entry))
    providers = config.get("providers")
    if isinstance(providers, dict):
        for key, entry in providers.items():
            if isinstance(entry, dict):
                name = str(entry.get("name") or key).strip()
                if name:
                    out.append((name, entry))
    return out


def _validate_provider_entry(name: str, entry: Dict[str, Any], errors: List[str], warns: List[str]) -> None:
    base_url = _entry_value(entry, "base_url", "url", "api", "baseUrl")
    if not base_url:
        errors.append(f"custom provider {name!r}: missing base_url")
    api_mode = _entry_value(entry, "api_mode", "transport", "apiMode")
    if api_mode is not None and str(api_mode or "").strip().lower() not in VALID_API_MODES:
        _validate_api_mode_value(api_mode, f"custom provider {name!r}: api_mode", errors)
    if not api_mode:
        warns.append(
            f"custom provider {name!r}: api_mode not set; "
            "Hermes will guess from URL, which is fragile"
        )
    if not _entry_has_auth(entry):
        warns.append(
            f"custom provider {name!r}: neither api_key nor key_env set; "
            "Hermes will use 'no-key-required' (OK for local servers, breaks hosted)"
        )
    models = entry.get("models")
    if isinstance(models, list):
        for item in models:
            if not isinstance(item, str) or not item.strip():
                errors.append(
                    f"custom provider {name!r}: models list entries must be non-empty strings"
                )
        warns.append(
            f"custom provider {name!r}: models is a list; Hermes accepts this, "
            "but per-model context_length/max_output_tokens are unavailable"
        )
    elif models is not None and not isinstance(models, dict):
        errors.append(
            f"custom provider {name!r}: models must be a mapping of model_id -> "
            "{{context_length, max_output_tokens}}, or a list of model ids"
        )
    elif isinstance(models, dict):
        for mid, mvals in models.items():
            if not isinstance(mvals, dict):
                errors.append(f"custom provider {name!r}: models.{mid} must be a mapping")
                continue
            ctx = mvals.get("context_length")
            mx = mvals.get("max_output_tokens")
            if ctx is not None and (not isinstance(ctx, int) or ctx <= 0):
                errors.append(
                    f"custom provider {name!r}: models.{mid}.context_length must be a positive int "
                    f"(got {ctx!r})"
                )
            if mx is not None and (not isinstance(mx, int) or mx <= 0):
                errors.append(
                    f"custom provider {name!r}: models.{mid}.max_output_tokens must be a positive int "
                    f"(got {mx!r})"
                )
    ctx_top = _entry_value(entry, "context_length", "contextLength")
    if ctx_top is not None and (not isinstance(ctx_top, int) or ctx_top <= 0):
        errors.append(
            f"custom provider {name!r}: context_length must be a positive int "
            f"(got {ctx_top!r})"
        )
    default_model = _entry_value(entry, "model", "default_model", "defaultModel")
    if default_model and isinstance(models, dict) and default_model not in models:
        warns.append(
            f"custom provider {name!r}: default model {default_model!r} is not listed "
            "in models — picker will show it but per-model context_length lookup will miss"
        )


def _validate_top_model(
    config: Dict[str, Any],
    provider_names: List[str],
    errors: List[str],
    warns: List[str],
) -> None:
    model = config.get("model")
    if not isinstance(model, dict):
        return
    provider = str(model.get("provider", "")).strip()
    if BUILTIN_PROVIDERS is not None and provider and provider.lower() not in BUILTIN_PROVIDERS:
        if provider.lower() not in {p.lower() for p in provider_names}:
            warns.append(
                f"model.provider {provider!r} is not a built-in alias and is not declared "
                f"in custom_providers/providers (known: {sorted(set(p.lower() for p in provider_names))})"
            )
    api_mode = model.get("api_mode")
    if api_mode is not None and str(api_mode or "").strip().lower() not in VALID_API_MODES:
        _validate_api_mode_value(api_mode, "model.api_mode", errors)
    for key in ("context_length", "max_tokens"):
        val = model.get(key)
        if val is not None and (not isinstance(val, int) or val <= 0):
            errors.append(f"model.{key} must be a positive int (got {val!r})")


def _validate_compression(config: Dict[str, Any], errors: List[str], warns: List[str]) -> None:
    comp = config.get("compression")
    if isinstance(comp, dict):
        thr = comp.get("threshold")
        if thr is not None:
            if not isinstance(thr, (int, float)) or not (0 < float(thr) <= 1.0):
                errors.append(
                    f"compression.threshold must be in (0, 1.0]; got {thr!r}"
                )
        for key in ("target_ratio",):
            val = comp.get(key)
            if val is not None and (
                not isinstance(val, (int, float)) or not (0 < float(val) <= 1.0)
            ):
                errors.append(f"compression.{key} must be in (0, 1.0]; got {val!r}")


def _validate_aux_compression(
    config: Dict[str, Any],
    provider_names: List[str],
    errors: List[str],
    warns: List[str],
) -> None:
    aux = config.get("auxiliary")
    if not isinstance(aux, dict):
        return
    comp = aux.get("compression")
    if not isinstance(comp, dict):
        return
    prov = str(comp.get("provider", "")).strip()
    if prov.startswith("custom:"):
        target = prov.split(":", 1)[1].strip().lower()
        known = {p.lower() for p in provider_names}
        if target and target not in known:
            errors.append(
                f"auxiliary.compression.provider {prov!r} references unknown custom provider "
                f"{target!r}; declared: {sorted(known)}"
            )
    api_mode = comp.get("api_mode")
    if api_mode is not None and str(api_mode or "").strip().lower() not in VALID_API_MODES:
        _validate_api_mode_value(api_mode, "auxiliary.compression.api_mode", errors)
    ctx = comp.get("context_length")
    if ctx is not None and (not isinstance(ctx, int) or ctx <= 0):
        errors.append(
            f"auxiliary.compression.context_length must be a positive int (got {ctx!r})"
        )
    main_ctx = (config.get("model") or {}).get("context_length")
    if isinstance(main_ctx, int) and isinstance(ctx, int) and ctx < main_ctx:
        warns.append(
            f"auxiliary.compression.context_length ({ctx}) is smaller than "
            f"model.context_length ({main_ctx}); summary calls may fail and "
            "middle turns will be dropped silently"
        )


def validate(path: Path) -> int:
    if not path.exists():
        print(f"config not found: {path}", file=sys.stderr)
        return 2
    try:
        config = _load_yaml(path)
    except Exception as exc:
        print(f"YAML parse error in {path}: {exc}", file=sys.stderr)
        return 2
    if not isinstance(config, dict):
        print(f"{path} is not a YAML mapping", file=sys.stderr)
        return 2

    errors: List[str] = []
    warns: List[str] = []

    cps_raw = config.get("custom_providers")
    if cps_raw is not None and not isinstance(cps_raw, list):
        errors.append(
            "custom_providers must be a YAML list (each entry prefixed with '-'); "
            f"got {type(cps_raw).__name__}"
        )
    providers_raw = config.get("providers")
    if providers_raw is not None and not isinstance(providers_raw, dict):
        errors.append(
            f"providers must be a YAML mapping; got {type(providers_raw).__name__}"
        )

    name_entries = _collect_custom_provider_names(config)

    seen_names: Dict[str, int] = {}
    for name, entry in name_entries:
        seen_names[name.lower()] = seen_names.get(name.lower(), 0) + 1
        _validate_provider_entry(name, entry, errors, warns)
    for name, count in seen_names.items():
        if count > 1:
            warns.append(
                f"provider {name!r} declared {count} times across custom_providers/providers; "
                "deduplicate or the picker will show repeats"
            )

    provider_names = [n for n, _ in name_entries]
    _validate_top_model(config, provider_names, errors, warns)
    _validate_compression(config, errors, warns)
    _validate_aux_compression(config, provider_names, errors, warns)

    for w in warns:
        print(f"warn: {w}", file=sys.stderr)
    for e in errors:
        print(f"error: {e}", file=sys.stderr)
    if errors:
        print(f"\nvalidate_config: {len(errors)} error(s), {len(warns)} warning(s) in {path}",
              file=sys.stderr)
        return 1
    print(f"validate_config: OK ({len(warns)} warning(s)) in {path}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--config", default=os.path.expanduser("~/.hermes/config.yaml"))
    args = p.parse_args(argv)
    return validate(Path(args.config))


if __name__ == "__main__":
    sys.exit(main())
