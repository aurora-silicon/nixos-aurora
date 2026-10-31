# Proposal: interface-owned ARP on laptop images

Status: draft for distro policy review; no sysctl or image default changes.

## Decision proposed

Use `arp_ignore=1` and `arp_announce=2` for ordinary physical Wi-Fi and
Ethernet interfaces on laptop images, consistently across Fedora, Arch Linux
ARM and NixOS. Keep the kernel defaults for generic routing/HA deployments.
Do not enable `arp_filter`: its routing-based decision needs source-policy
routing when interfaces share a subnet.

A laptop with Wi-Fi and a dock on the same IPv4 subnet can currently answer
ARP for its Wi-Fi address on Ethernet. A peer then caches the dock MAC for
the Wi-Fi address, and a benchmark bound only to that source address can
receive its bulk traffic over Ethernet. This follows the Linux default
host-wide ownership model; it is not a brcmfmac packet-routing defect.

`arp_ignore=1` limits replies to addresses assigned to the receiving
interface. `arp_announce=2` selects an appropriate local address on the
outgoing interface for ARP requests; it avoids announcing the other
interface's address in the common numbered-interface case. It is not an
absolute ban on cross-interface announcements when no suitable address exists.
Level 2 for `arp_ignore` adds a sender-subnet restriction that is unnecessary
for this problem and could reject legitimate off-subnet requesters.

## Integration and exceptions

Scope the eventual implementation to managed physical client links. Leave
`conf.all.arp_ignore` and `conf.all.arp_announce` at their existing defaults
(normally zero), and apply the per-link values through the distro's network
lifecycle integration, including dock hotplug. Do not raise `conf.all` as a
shortcut: both controls use the maximum of `all` and the interface value,
so that would prevent a per-interface exception. Likewise, a blanket
`conf.default` change would affect future bridges, tunnels and HA links.

An explicit network profile may retain the upstream host-wide behavior for
floating addresses, HA/VRRP, loopback-owned service addresses, deliberate
asymmetric reachability, or unnumbered links. Document that exception in the
network configuration, rather than adding an Aurora tuning interface.
Preserve administrator values, configuration precedence and removal behavior.
Do not change SSIDs, addresses, routes, reverse-path filtering or IPv6 policy
as part of this proposal.

| Distribution | Proposed integration, subject to review |
| --- | --- |
| Fedora | Physical client links managed by NetworkManager; include reapply and dock hotplug, without rewriting saved connection secrets. |
| Arch Linux ARM | Same NetworkManager behavior on the default laptop image; leave custom network stacks to their administrator. |
| NixOS | Declarative equivalent for the selected networking backend; support both initial activation and hotplug, with normal NixOS override precedence. |

The backend hook and ownership/removal contract need review before code is
added. This document intentionally installs nothing.

## Validation required before enabling

1. Use two distinct IPv4 addresses on two physical links on the same subnet.
   From a peer with a fresh test-address neighbour entry, solicit each address
   and verify replies use only the MAC of the interface owning that address.
2. Send traffic bound to each interface as well as to its source address;
   record counters on both laptop interfaces and the peer's neighbour table.
   ARP controls alone do not enforce a strong IP receive model or policy
   routing. A stale peer cache can still send frames to the old MAC.
3. Exercise Wi-Fi-only, Ethernet-only, both connected, dock unplug/replug,
   DHCP renewal, suspend/resume and reboot. Verify ordinary reachability,
   administrator overrides, and the HA/profile exception.
4. Validate outgoing ARP source selection and confirm IPv6 ND is unchanged.
   A global IPv6 ND failure needs a separate diagnosis; these IPv4 controls
   cannot fix it.
5. Run the same matrix on all three images before advancing the proposal.
   Preserve before/after values; rollback only the values owned by this policy
   and restore the previous profile without removing unrelated sysctls.

For wireless benchmarking, bind the interface (for example iperf3
`--bind-dev` where available), verify peer neighbour entries and measure
both interfaces' byte counters. Binding a source IP is insufficient proof
of the path. Link-local IPv6 with an explicit zone provides a useful control.

## Source

The behavior and maximum-value precedence above follow the upstream
[Linux IP sysctl documentation](https://docs.kernel.org/networking/ip-sysctl.html)
(`arp_ignore`, `arp_announce`, `arp_filter`). This proposal includes no local
lab configuration, addresses, private captures or machine-specific workaround.
