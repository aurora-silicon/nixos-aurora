# Aurora SEP integration

The shared kernel builds SEP as a module. The root filesystem supplies the
identity state, boot-container device link and per-device calibration, so an
early built-in probe cannot initialize the driver reliably.

The boot timer starts the loader after local filesystems are available, without
holding up the desktop. fprintd also joins initialization when requested. The
modprobe alias blacklist only defers automatic probing: the service explicitly
loads SEP on every supported boot. Dracut omits the module from the initramfs.

Calibration extraction reads the local boot container without modifying it. A
private cache is bound to its partition identity and SHA-256. The device-tree
firmware name is respected. No calibration data is distributed or reused across
machines. Models without a fingerprint reader can still initialize SEP trusted
keys; missing calibration is reported without suppressing the cryptographic
services. Read XART-SAFETY.md for persistent identity ownership constraints.

The Aurora libfprint build keeps the full upstream driver set and adds the SEP
biometric interface. This package does not edit PAM, replace password login or
change the power-button action. Use the desktop's fingerprint enrollment flow
once hardware qualification is complete. Module reload cannot repeat the secure
enclave handoff; driver updates take effect after a full reboot.
