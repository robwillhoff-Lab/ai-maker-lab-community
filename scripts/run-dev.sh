#!/bin/sh
# Runs only the repository source; never installs or modifies desktop settings.
set -eu
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$repo/src"
exec python3 -B -m ai_maker_lab "$@"
