#!/bin/bash
# Wake for network access, as macOS laptops default to it: on while on the
# power adapter, off on battery. Arms magic-packet wake on every wired
# interface that supports it (Wake-on: g) and on every Wi-Fi phy whose driver
# offers magic-packet WoWLAN; disarms them on battery.
#
# Run by udev when the adapter state changes and when a network device
# appears. /etc/aurora/wake-for-network overrides the policy with one word:
#   power-adapter (default), always, never
# NetworkManager leaves both settings alone unless a connection sets
# ethernet.wake-on-lan or wifi.wake-on-wlan itself, which then wins at its
# next activation.
set -u
export PATH=/usr/sbin:/usr/bin

policy=power-adapter
if [ -r /etc/aurora/wake-for-network ]; then
	read -r policy < /etc/aurora/wake-for-network || true
fi

on_adapter() {
	local ps have_mains=0
	for ps in /sys/class/power_supply/*; do
		[ -r "$ps/type" ] || continue
		[ "$(cat "$ps/type")" = Mains ] || continue
		have_mains=1
		[ "$(cat "$ps/online" 2>/dev/null)" = 1 ] && return 0
	done
	# No adapter reported at all: treat it as a desktop on mains power.
	[ $have_mains = 0 ]
}

case $policy in
always) arm=1 ;;
never) arm=0 ;;
*) if on_adapter; then arm=1; else arm=0; fi ;;
esac

for n in /sys/class/net/*; do
	[ -e "$n/device" ] || continue
	[ -d "$n/wireless" ] && continue
	ifc=${n##*/}
	ethtool "$ifc" 2>/dev/null | grep -q '^[[:space:]]*Supports Wake-on:.*g' || continue
	if [ $arm = 1 ]; then ethtool -s "$ifc" wol g; else ethtool -s "$ifc" wol d; fi
done

for p in /sys/class/ieee80211/*; do
	[ -e "$p" ] || continue
	phy=${p##*/}
	iw phy "$phy" info 2>/dev/null | grep -A8 'WoWLAN support' | grep -qi 'magic packet' || continue
	if [ $arm = 1 ]; then iw phy "$phy" wowlan enable magic-packet; else iw phy "$phy" wowlan disable; fi
done
exit 0
