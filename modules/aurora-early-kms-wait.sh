# The body of aurora-kms-handover (boot-splash.nix), which sets its PATH.
# Runs in the initramfs just before the pivot: hand the splash over to the
# display driver before leaving the initramfs.
#
# appledrm registers its DRM device once every display coprocessor is up,
# which can be after the root file system is ready. If the initramfs pivots
# first, udevd is gone when the device appears: Plymouth only hears of it
# from the real root's udevd, about half a second later, and in between an
# external display's hotplug makes the kernel's fbdev emulation, which then
# has no DRM master to defer to, light every output with its own empty
# buffer: the panel flashes black before the splash comes back.
#
# Wait for udev to announce the display subsystem's card, so Plymouth opens
# it (and holds DRM master) while the initramfs udevd still runs. udevadm
# wait returns on udev's own event for the card, or at once if udev has
# announced it already; nothing polls. The wait is bounded at 2 s; how long
# it lasts is how late the kernel registers the card.
#
# No wait when no card can come: without the display subsystem, or when no
# driver is bound to it and none can bind. "Not bound yet" is not "cannot
# bind": the driver's module may still be loading from the coldplug, or its
# probe may be deferred on a supplier, and that is the case the wait is for.
# So an unbound subsystem is asked for its modalias: a driver can bind when
# a module of this initramfs matches it and is not blacklisted (modprobe.d,
# modprobe.blacklist=, rd.driver.blacklist=, module_blacklist=).
#
# This file is the same in fedora-aurora, alarm-aurora and nixos-aurora
# apart from the first line (tests pin it).

# Print the names that may not load ('-' or '_', comma or line separated):
# modprobe's own list (modprobe.d and modprobe.blacklist=), then the kernel
# command line $1. In a subshell: set -f stays here.
aurora_early_kms_blacklist() (
    set -f
    modprobe -c 2>/dev/null | while read -r key name _; do
        [ "$key" != blacklist ] || printf '%s\n' "$name"
    done
    [ -r "$1" ] || exit 0
    read -r line < "$1"
    for arg in $line; do
        case "$arg" in
            modprobe.blacklist=*|rd.driver.blacklist=*|module_blacklist=*)
                printf '%s\n' "${arg#*=}" ;;
        esac
    done
)

# Can a driver bind to the platform device $1? $2 is the kernel command line.
aurora_early_kms_can_bind() {
    local alias module blacklist

    [ -e "$1/driver" ] && return 0
    [ -r "$1/modalias" ] || return 1
    read -r alias < "$1/modalias" || return 1
    blacklist=" $(aurora_early_kms_blacklist "$2" | tr ',\n-' '  _') "
    for module in $(modprobe -R "$alias" 2>/dev/null | tr - _); do
        case "$blacklist" in
            *" $module "*) ;;
            *) return 0 ;;
        esac
    done
    return 1
}

# $1 is sysfs and $2 the kernel command line (the tests pass their own).
aurora_early_kms_wait() {
    local sysfs="${1:-/sys}" cmdline="${2:-/proc/cmdline}" dev

    for dev in "$sysfs"/bus/platform/devices/*display-subsystem; do
        [ -e "$dev" ] && break
    done
    [ -e "$dev" ] || return 0
    aurora_early_kms_can_bind "$dev" "$cmdline" || return 0

    # 60-drm.rules links each platform card as
    # /dev/dri/by-path/platform-<device>-card.
    udevadm wait --timeout=2 "/dev/dri/by-path/platform-${dev##*/}-card" 2>/dev/null
    return 0
}

aurora_early_kms_wait
