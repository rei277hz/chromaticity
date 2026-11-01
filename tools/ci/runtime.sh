#!/usr/bin/env bash
# Run only from a disposable checkout: selecting local execution rewrites .buckconfig.
set -euo pipefail

if [[ ${CI_DISPOSABLE_CHECKOUT:-} != 1 ]]; then
  echo 'Set CI_DISPOSABLE_CHECKOUT=1 only in a disposable checkout; this command selects local Buck execution.' >&2
  exit 2
fi
if [[ $# -eq 0 ]]; then
  echo 'Usage: tools/ci/runtime.sh COMMAND [ARG ...]' >&2
  exit 2
fi
: "${CI_CACHE_DIR:?Set CI_CACHE_DIR to a persistent CI cache directory outside the checkout}"

ci_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)
ci_buck2=${CI_BUCK2_BINARY:-$(command -v buck2 || true)}
if [[ -z $ci_buck2 || ! -x $ci_buck2 ]]; then
  echo 'Install the pinned standalone Buck2 binary with tools/ci/install_tools.py first.' >&2
  exit 2
fi
ci_buck2=$(readlink -f -- "$ci_buck2")
if [[ $ci_buck2 == /nix/store/* ]]; then
  echo 'The container needs the standalone Buck2 release binary, not a Nix binary. Set CI_BUCK2_BINARY accordingly.' >&2
  exit 2
fi

mkdir -p -- "$CI_CACHE_DIR"
ci_cache=$(cd -- "$CI_CACHE_DIR" && pwd -P)
case "$ci_cache/" in
  "$ci_root/"*)
    echo 'CI_CACHE_DIR must be outside the source checkout.' >&2
    exit 2
    ;;
esac
mkdir -p -- "$ci_cache/home" "$ci_cache/xdg" "$ci_cache/cargo" "$ci_cache/rust-catalogue"
# Docker must not create this bind-mount destination as root in the checkout.
mkdir -p -- "$ci_root/third_party/rust/.cargo"

ci_image=${CI_RUNTIME_IMAGE:-perceptual-grade-ci-runtime}
docker build --platform linux/amd64 --target ci --tag "$ci_image" "$ci_root/remote_execution/docker"
exec docker run --rm --init --platform linux/amd64 \
  --ulimit nofile=65536:65536 \
  --user "$(id -u):$(id -g)" \
  --mount "type=bind,src=$ci_root,dst=/workspace" \
  --mount "type=bind,src=$ci_buck2,dst=/usr/local/bin/buck2,readonly" \
  --mount "type=bind,src=$ci_cache,dst=/cache" \
  --mount "type=bind,src=$ci_cache/rust-catalogue,dst=/workspace/third_party/rust/.cargo" \
  --env HOME=/cache/home \
  --env XDG_CACHE_HOME=/cache/xdg \
  --env CARGO_HOME=/cache/cargo \
  --env BUCK_ISOLATION_DIR=ci \
  --env BUCK_NO_INTERACTIVE_CONSOLE=1 \
  --workdir /workspace --entrypoint /bin/bash \
  "$ci_image" -euo pipefail -c '
    ./remote_execution/re local
    python3 tools/ci/check_targets.py
    exec "$@"
  ' ci-command "$@"
