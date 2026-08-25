#!/usr/bin/env bash
# Wrapper around the trimmed ZEsarUX binary: points it at the bundled
# SDL1.2/SDL2 shim libraries (required even in headless --vo null mode)
# and forwards all arguments untouched.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export LD_LIBRARY_PATH="$HERE/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
exec "$HERE/zesarux" --noconfigfile "$@"
