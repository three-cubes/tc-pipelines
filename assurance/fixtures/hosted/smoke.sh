#!/usr/bin/env bash
set -euo pipefail
observed="$(docker run --rm "tc-assurance-fixture:${ASSURANCE_IMAGE_TAG:?}")"
test "$observed" = fresh-install-fixture
docker image inspect "tc-assurance-fixture:${ASSURANCE_IMAGE_TAG}" --format '{{.Id}}'
