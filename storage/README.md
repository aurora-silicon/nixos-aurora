# Apple ANS storage default

Select `none` on NVMe namespace disks whose ancestor driver is `nvme-apple`.
Partitions, USB disks and PCI NVMe controllers do not match. The rule only
selects an available scheduler; it leaves request-size limits, read-ahead,
merging, CPU/IRQ affinity and polling at their kernel defaults.

ANS exposes one I/O hardware queue and a shared interrupt. `none` removes the
scheduler's dispatch policy from that path. This is a candidate performance
default: it needs matched latency, throughput and contention benchmarks before
merge. It does not establish that scheduling caused any filesystem tail latency.

The same rule is carried by Fedora, ALARM and NixOS Aurora. RPM/ALARM updates
install the rule without triggering existing devices; the next boot or device
add/change applies it. An administrator can override the vendor rule using the
same filename under `/etc/udev/rules.d/` (including a symlink to `/dev/null`).
NixOS also exposes `aurora.storage.appleNvmeScheduler` to omit the rule.
Removing or masking the rule does not reset the live scheduler; restore the
previous scheduler explicitly during an approved experiment, or reboot with
the previous configuration. Do not claim rollback from package removal alone.

## Benchmark before merging

Use fio's psync engine with `thread=1`, `direct=1`, `group_reporting=1`,
a 3 GiB prefilled scratch file, 15 seconds after a 2-second ramp. Keep file,
filesystem, allocation policy, fio version and data pattern fixed between
scheduler arms. In this method QD32 means 32 synchronous jobs, each at depth 1.

Interleave at least five `mq-deadline`/`none` pairs on each supported machine:
1 MiB sequential reads with 1 and 8 jobs; 4 KiB random reads and writes with
1 and 32 jobs. Keep random seed sequences paired and include a repeat with
the original non-repeating seeds. Preserve all JSONs, achieved depth, p50,
p95, p99, p99.9, throughput, CPU cost and errors. Measure an application reader
against background writes separately to expose fairness/tail regressions.
Record original settings and restore them in a finally/trap path. Only write
to explicitly owned scratch files within the allocation budget, never a raw
device. Raw read controls must use readonly and disallow file creation.

Keep polling and IRQ/CPU affinity as separate experiments. Current ANS exposes
no blk-mq poll map, so application IOPOLL requires driver work first; a sysfs
write cannot enable it. Treat the following polling comparison as conditional. psync does not issue
polled I/O; compare io_uring at depth 1/32 without polling against otherwise
identical io_uring IOPOLL runs before attributing gains to polling. Do not
compare psync directly to a different engine and call the delta a polling win.
A 1 MiB request-size limit already covers a 1 MiB I/O; trace actual request
sizes and segment splits before proposing a larger limit. Direct I/O does not
use buffered read-ahead.
