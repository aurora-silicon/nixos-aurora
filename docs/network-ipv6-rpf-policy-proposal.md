# Proposal: IPv6 source validation for multihomed laptop images

Status: draft; image and installed-host defaults are unchanged.

## Proposed policy

Use loose IPv6 reverse-path validation for laptop client networking while
keeping the firewall enabled. A source must remain reachable through a route,
but the best reverse route need not use the ingress interface. Preserve an
administrator's explicit strict policy and the existing firewall service and
port rules. Routing/security appliances need their own deliberate policy.

This is separate from [IPv4 ARP ownership](network-arp-policy-proposal.md).
Changing ARP sysctls cannot repair an IPv6 reverse-path drop.

## Failure mechanism

When Wi-Fi and Ethernet share an IPv6 prefix, the preferred reverse route to
a peer can use Ethernet even for a socket bound to Wi-Fi. Firewalld strict
RPF evaluates the ingress interface as part of the reverse lookup. A global
packet arriving over Wi-Fi can therefore be dropped before local ICMPv6
processing. Link-local traffic can work because its reverse lookup is scoped
to the link.

Firewalld's nftables backend exempts neighbour solicitations and router
advertisements from that RPF check, but not neighbour advertisements. Thus a
peer may learn the laptop's Wi-Fi address from its replies to solicitations,
while the laptop fails to learn the peer's global address because the peer's
advertisements fail strict RPF. This asymmetry is not proof of a radio or
firmware multicast defect. Read the active rules before attributing the drop.

## Distribution integration to review

Fedora already proposed loose IPv6 RPF for Workstation in Fedora 42. Audit
the selected base/profile and packaged defaults before adding an Aurora
setting. An installed strict configuration can be an intentionally preserved
administrator file; do not rewrite it on upgrade. A fresh image should inherit
the appropriate workstation policy from the supported package/profile.

Arch Linux ARM should apply an equivalent loose policy only if its chosen
firewall installs IPv6 RPF. Do not add firewalld just to set this option.
NixOS should express equivalent behavior using its selected firewall backend
and normal declarative override precedence. Do not assume the three backends
use the same option or that an already-loose backend needs a change.

## Acceptance and rollback

Before implementation, inspect the live rules and reverse lookup on each
image. In an isolated namespace, give Wi-Fi and Ethernet the same prefix with
Ethernet preferred, then compare bound global ND/ICMP with link-local traffic.
Record RPF drop counters and verify that loose validation admits the global
reply without opening a service or disabling the firewall. Repeat with the
preferred link removed and with each link reconnected. Confirm an explicitly
strict administrator policy survives upgrades and activation.

For a target A/B test, any temporary exception needs scoped authorization and
exact restoration of the original rule/configuration. Keep that local test
out of packages. Future image changes should own only the new-image default;
rollback must not overwrite administrator firewall policy.

## Public references

- [firewalld configuration manual](https://firewalld.org/documentation/man-pages/firewalld.conf)
- [firewalld nftables RPF implementation](https://github.com/firewalld/firewalld/blob/main/src/firewall/core/nftables.py)
- [Fedora Workstation loose-RPF change](https://fedoraproject.org/wiki/Changes/Firewalld_IPv6_rpfilter_Default_Loose)

This proposal contains no per-machine addresses, local overrides or lab captures.
