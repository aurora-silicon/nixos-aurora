#!/usr/bin/env bash
# Build ctxr/boot-ctxr-<board>.bin and a digest beside each, for the Macs that
# boot m1n1/boot-ctxr.bin. This runs on every Mac's rebuild, so a problem here
# only warns and leaves that board's file out. aurora-install-stage2 warns on the
# Mac that needs a missing file.
#
#   build-ctxr-stage2.sh CHECK_STAGE2 PREPARE_STAGE2 PREPARE_CTXR BOOT_BIN AURA OUTPUT
set -uo pipefail

check_stage2=$1
prepare_stage2=$2
prepare_ctxr=$3
boot_bin=$4
aura=$5
output=$6

warn() {
  echo "build-ctxr-stage2: warning: $*" >&2
}

boards=$(mktemp -d)
mkdir -p "$output"
if ! python3 "$prepare_stage2" --combined "$boot_bin" --aura "$aura" \
  --output "$boards" --manifest "$boards.json"; then
  warn 'could not split the combined Stage 2, so this build has no Mach-O Stage 2 files'
  exit 0
fi
if ! python3 "$prepare_ctxr" --keep-going "$boards" "$output"; then
  warn 'could not prepare the Mach-O Stage 2 files'
  exit 0
fi
for image in "$output"/*.bin; do
  [[ -e $image ]] || continue
  if python3 "$check_stage2" --stage2 "$image" --aura "$aura" > /dev/null; then
    sha256sum "$image" | cut -d' ' -f1 > "$image.sha256"
  else
    warn "${image##*/} failed its check, so it has no digest and won't be installed"
  fi
done
