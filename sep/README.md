# Aurora SEP integration

The shared kernel builds SEP as a module. The root filesystem supplies the
identity state, boot-container device link and per-device calibration, so an
early built-in probe cannot initialize the driver reliably.

An older running kernel with SEP built in is skipped until the module-based
kernel boots.

The boot timer starts the loader after local filesystems are available, without
holding up the desktop. fprintd also joins initialization when requested. The
modprobe alias blacklist only defers automatic probing: the service explicitly
loads SEP on every supported boot. Fedora uses Dracut to omit the module from the initramfs.

Each start rebuilds the fingerprint calibration from this Mac's own factory
records, read without modification from the Hardware volume of its iBoot System
Container: the calibration resealed with the seal that names this Mac's chip
and ECID, and the trust bundle in use. The installed record is replaced only
when it differs; the replaced bytes are kept privately as rollback evidence,
and a record that is refused moves to private quarantine. Touch ID is marked
ready in /run/aurora-sep only when the installed record is the one admitted, and
fprintd and the reader activation wait for that. The device-tree firmware name
is respected. No calibration data is distributed or reused across machines. Models without a fingerprint reader can still initialize SEP trusted
keys; missing calibration is reported without suppressing the cryptographic
services. Read XART-SAFETY.md for persistent identity ownership constraints.

The Aurora libfprint build keeps the full upstream driver set and adds the SEP
biometric interface. This package does not edit PAM, replace password login or
change the power-button action. Use the desktop's fingerprint enrollment flow
once hardware qualification is complete. Module reload cannot repeat the secure
enclave handoff; driver updates take effect after a full reboot.
