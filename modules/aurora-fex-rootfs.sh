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

# The provider, mounted, with Aurora's Mesa layer over the guest root
# filesystem: the x86-64 dynamic loader (where Fedora or Arch keep it) and, in
# the same directory, an x86-64 (64-bit ELF) Vulkan driver from the layer.
# Without a lower layer the overlay holds only Mesa, and a layer laid out for
# another distribution's directories puts its i686 driver there.
usable() {
	mountpoint -q "$provider" && [ -e "$provider/.aurora-mesa-commit" ] || return 1
	for lib in usr/lib64 usr/lib; do
		[ -e "$provider/$lib/ld-linux-x86-64.so.2" ] || continue
		[ "$(od -An -N5 -tx1 "$provider/$lib/libvulkan_asahi.so" 2>/dev/null | tr -d ' \n')" = 7f454c4602 ]
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
	if ! mount --bind -o ro "$provider" "$rootfs"; then
		rm -f "$config"
		exit 1
	fi
fi
tmp=$(mktemp "$dir/.Config.json.XXXXXX") || exit 1
printf '{\n  "Config": {\n    "RootFS": "%s"\n  }\n}\n' "$rootfs" >"$tmp"
chmod 644 "$tmp"
# Renamed into place: FEX refuses to start on a partly written config.
mv -f "$tmp" "$config"
