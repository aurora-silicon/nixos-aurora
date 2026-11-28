# Point FEX's global RootFS at Aurora's FEX guest graphics provider while the
# provider is mounted, and drop it when it isn't. aurora-fex-mesa.service runs
# this after it mounts and after it unmounts the provider (modules/fex-mesa.nix).
#
# FEX reads /run/fex-emu/Config.json over its global config
# (patches/fex-runtime-config.patch), and a user's own Config.json and
# FEX_ROOTFS override both. Without that file FEX uses the user's RootFS, as
# before.
#
# FEX gets a bind mount of the provider, /run/fex-emu/rootfs, rather than the
# provider's own mount point. Running x86 programs keep their RootFS busy, and
# the provider must unmount when a switch changes its layer. A bind still in use
# stays mounted for those programs, below a new one if the provider comes back;
# nothing new is pointed at it.
set -u
provider=/var/lib/aurora/fex/mesa-rootfs
dir=/run/fex-emu
rootfs=$dir/rootfs
config=$dir/Config.json
tmp=

# Leave FEX without a runtime RootFS (a user's own one still applies), and
# say why (the journal, from the service).
fail() {
	echo "aurora-fex-rootfs: $*; FEX gets no runtime RootFS" >&2
	[ -z "$tmp" ] || rm -f "$tmp"
	rm -f "$config"
	exit 1
}

# An x86-64 ELF file: 64-bit, little-endian, e_machine 62 (EM_X86_64).
x86_64() {
	case $(od -An -N20 -tx1 "$1" 2>/dev/null | tr -d ' \n') in
	7f454c460201????????????????????????3e00) return 0 ;;
	esac
	return 1
}

# The provider, mounted, with Aurora's Mesa layer over the guest root
# filesystem: the x86-64 dynamic loader (where Fedora or Arch keep it) and, in
# the same directory, the layer's x86-64 Vulkan driver. Without a lower layer
# the overlay holds only Mesa, and a layer laid out for another distribution's
# directories puts its i686 driver there.
usable() {
	mountpoint -q "$provider" && [ -e "$provider/.aurora-mesa-commit" ] || return 1
	for lib in usr/lib64 usr/lib; do
		[ -e "$provider/$lib/ld-linux-x86-64.so.2" ] || continue
		x86_64 "$provider/$lib/libvulkan_asahi.so"
		return
	done
	return 1
}

# Unmount the binds nothing uses, newest first; one in use is busy and stays,
# with any below it.
release() {
	while mountpoint -q "$rootfs"; do
		umount "$rootfs" 2>/dev/null || break
	done
}

if ! usable; then
	rm -f "$config"
	release
	exit 0
fi

mkdir -p "$rootfs"
chmod 755 "$dir"
# The same file system on both paths: the bind already shows this mount.
if ! mountpoint -q "$rootfs" || [ "$(stat -c %d "$rootfs")" != "$(stat -c %d "$provider")" ]; then
	release
	mount --bind -o ro,nosuid,nodev "$provider" "$rootfs" || fail "can't bind-mount $provider at $rootfs"
fi
# Read-only, nosuid and nodev, as the provider is. Set them on the bind in
# place too: a bind kept from an earlier start may have been made without them.
mount -o remount,bind,ro,nosuid,nodev "$rootfs" ||
	fail "can't make $rootfs read-only, nosuid and nodev"
# FEX refuses to start on an empty or partly written config: write it in full
# beside the old one, check it, then rename it into place. A full /run leaves
# no config at all.
want=$(printf '{\n  "Config": {\n    "RootFS": "%s"\n  }\n}' "$rootfs")
tmp=$(mktemp "$dir/.Config.json.XXXXXX") || { tmp=; fail "can't create a file in $dir"; }
printf '%s\n' "$want" >"$tmp" || fail "can't write $tmp"
[ "$(cat "$tmp")" = "$want" ] || fail "$tmp doesn't hold the whole config"
chmod 644 "$tmp" || fail "can't set the mode of $tmp"
mv -f "$tmp" "$config" || fail "can't rename $tmp to $config"
