#!/usr/bin/env bash
# Backup / restore / verify for ~/.hermes/config.yaml and ~/.hermes/.env.
#
# Usage:
#   backup_restore.sh backup [tag]              -> writes timestamped backups
#   backup_restore.sh restore <backup-tag>      -> restores files for the given tag
#   backup_restore.sh verify  <backup-tag>      -> compares current file to backup
#   backup_restore.sh list                      -> lists backups created by this skill
#
# Backups go under ~/.hermes/backups/hermes-model-config/<tag>/.
# Tags default to a timestamp like 20260523_065900.

set -euo pipefail

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
CONFIG="$HERMES_HOME/config.yaml"
ENVFILE="$HERMES_HOME/.env"
ROOT="$HERMES_HOME/backups/hermes-model-config"

cmd="${1:-}"
shift || true

usage() {
    sed -n '2,12p' "$0"
    exit 2
}

case "$cmd" in
    backup)
        tag="${1:-$(date +%Y%m%d_%H%M%S)}"
        dest="$ROOT/$tag"
        mkdir -p "$dest"
        if [[ -e "$CONFIG" ]]; then
            cp -p "$CONFIG" "$dest/config.yaml"
            echo "backed up config.yaml  -> $dest/config.yaml"
        else
            echo "warn: $CONFIG does not exist; nothing to back up" >&2
        fi
        if [[ -e "$ENVFILE" ]]; then
            cp -p "$ENVFILE" "$dest/.env"
            echo "backed up .env         -> $dest/.env"
        else
            echo "note: $ENVFILE does not exist; skipping" >&2
        fi
        # Capture sha256 sums for verify.
        (
            cd "$dest"
            ls config.yaml .env 2>/dev/null | xargs sha256sum > sha256sum.txt 2>/dev/null || true
        )
        echo "tag: $tag"
        ;;

    restore)
        tag="${1:-}"
        [[ -z "$tag" ]] && usage
        src="$ROOT/$tag"
        if [[ ! -d "$src" ]]; then
            echo "no such backup tag: $src" >&2
            exit 2
        fi
        if [[ -f "$src/config.yaml" ]]; then
            cp -p "$src/config.yaml" "$CONFIG"
            echo "restored config.yaml from $src/config.yaml"
        fi
        if [[ -f "$src/.env" ]]; then
            cp -p "$src/.env" "$ENVFILE"
            echo "restored .env from $src/.env"
        fi
        ;;

    verify)
        tag="${1:-}"
        [[ -z "$tag" ]] && usage
        src="$ROOT/$tag"
        if [[ ! -d "$src" ]]; then
            echo "no such backup tag: $src" >&2
            exit 2
        fi
        diffs=0
        for f in config.yaml .env; do
            src_file="$src/$f"
            cur_file="$HERMES_HOME/$f"
            if [[ -f "$src_file" && ! -f "$cur_file" ]]; then
                echo "MISSING $f"
                diffs=$((diffs+1))
                continue
            fi
            if [[ ! -f "$src_file" && -f "$cur_file" ]]; then
                echo "EXTRA $f"
                diffs=$((diffs+1))
                continue
            fi
            if [[ ! -f "$src_file" && ! -f "$cur_file" ]]; then
                echo "ABSENT $f"
                continue
            fi
            if ! cmp -s "$src_file" "$cur_file"; then
                echo "DIFF $f"
                diff -u "$src_file" "$cur_file" | sed -n '1,40p' || true
                diffs=$((diffs+1))
            else
                echo "MATCH $f"
            fi
        done
        if [[ $diffs -gt 0 ]]; then
            echo "verify: $diffs file(s) differ from backup $tag" >&2
            exit 3
        fi
        echo "verify: current files identical to backup $tag"
        ;;

    list)
        [[ -d "$ROOT" ]] || { echo "no backups under $ROOT"; exit 0; }
        ls -1 "$ROOT"
        ;;

    *)
        usage
        ;;
esac
