#!/usr/bin/env bash
# Shared implementation for the license-present composite and tc-pipelines'
# local fitness step. Inputs arrive only through environment variables.

set -euo pipefail

: "${LICENSE_FILE:=LICENSE}"
: "${SPDX_ID:=Apache-2.0}"

if [[ ! -f "$LICENSE_FILE" ]]; then
  echo "::error::license-present: '$LICENSE_FILE' missing." \
    "fix: add a top-level $LICENSE_FILE declaring $SPDX_ID." >&2
  exit 1
fi

if grep -qiF "SPDX-License-Identifier: ${SPDX_ID}" "$LICENSE_FILE"; then
  echo "license-present: '$LICENSE_FILE' declares $SPDX_ID (SPDX line)."
  exit 0
fi

marker_a=""
marker_b=""
case "$SPDX_ID" in
  Apache-2.0) marker_a="Apache License"; marker_b="Version 2.0" ;;
  MIT) marker_a="MIT License"; marker_b="Permission is hereby granted" ;;
  BSD-3-Clause) marker_a="Redistribution and use"; marker_b="Neither the name" ;;
  BSD-2-Clause) marker_a="Redistribution and use"; marker_b="THIS SOFTWARE IS PROVIDED" ;;
  GPL-3.0-only|GPL-3.0-or-later) marker_a="GNU GENERAL PUBLIC LICENSE"; marker_b="Version 3" ;;
  MPL-2.0) marker_a="Mozilla Public License"; marker_b="Version 2.0" ;;
  *)
    echo "::error::license-present: SPDX id '$SPDX_ID' not recognised." \
      "fix: add an 'SPDX-License-Identifier: $SPDX_ID' line to '$LICENSE_FILE'," \
      "or extend the action's known-id table." >&2
    exit 1
    ;;
esac

if grep -qF "$marker_a" "$LICENSE_FILE" && grep -qF "$marker_b" "$LICENSE_FILE"; then
  echo "license-present: '$LICENSE_FILE' matches $SPDX_ID (body markers)."
  exit 0
fi

echo "::error::license-present: '$LICENSE_FILE' is not $SPDX_ID" \
  "(expected markers '$marker_a' + '$marker_b', or an" \
  "'SPDX-License-Identifier: $SPDX_ID' line). fix: replace" \
  "'$LICENSE_FILE' with the correct $SPDX_ID text." >&2
exit 1
