# Native GL default qualification and rollout (draft)

Factory images leave GL/GLES driver selection to Mesa. Zink remains packaged
as an application fallback. `scripts/check-basics.py` checks the finished root
for a global `MESA_LOADER_DRIVER_OVERRIDE` or `GALLIUM_DRIVER` in PAM, session
and environment.d files, including NixOS store-backed configuration. Empty
values and comments do not force a driver. The check never edits an installed
system or its local configuration.

The current public packaging does not set a global Zink override. There is no
package-owned assignment to delete. A Zink assignment added locally remains
local until its configuration owner removes it after qualification. Do not add
a package upgrade hook which silently rewrites that file.

## Qualification prerequisite

Use the [Mesa native GL qualification kit](https://github.com/aurora-silicon/mesa/tree/fu-native-gl-default-t3627/src/asahi/tools/native-gl-qualification)
with the final reviewed source commit and matching distribution build. Mesa
[PR 116](https://github.com/aurora-silicon/mesa/pull/116) is a prerequisite;
stacking a new candidate does not qualify or merge it. Record the following
results before accepting this rollout:

- GLES2, GLES3 and GLES31 complete frozen lists, matching results and no new
  failures, timeouts, crashes or unexpected loss of supported tests.
- Focused Piglit, sample-mask and sparse-buffer cases. Sparse-buffer unsupported
  on native GL is not a passing result. Any test-bug waiver needs spec evidence.
- All fourteen aligned/misaligned U8/U16/U32 strip draws, including GPU-copy
  writers, cover all 4096 pixels on both paths.
- Software-FP64 subroutine-array compile times on both drivers. Native advertises
  software doubles, so reachability must not be assumed away.
- A fresh native user compositor and a separately verified native GDM greeter,
  including the circular avatar and loaded candidate library identity.
- Paired native/Zink glmark2-es2 scores and CPU times without a loss beyond run
  noise. The public gpubench has no GL executor; its Vulkan numbers are not a
  native-GL versus Zink comparison. Record that requested metric as unavailable.
- Installed driver selection and rollback on each distribution. An overlay
  result alone does not qualify an installed image or a different libc closure.

Do not advance the Mesa source pin merely to enable this policy. The draft
remains pending until the final candidate has passed these checks. No device
qualification or performance scores are claimed by this documentation.

## Existing configuration migration after qualification

On Fedora and ALARM, save `/etc/environment` with its original ownership and
mode. Remove only the exact `MESA_LOADER_DRIVER_OVERRIDE=zink` assignment and an
accompanying exact `GALLIUM_DRIVER=zink` assignment, if present. Preserve every
unrelated line. Check session environment.d selectors separately. Restart the
display manager or reboot during the approved configuration-test reservation,
then verify the **greeter and user session**, without overlay variables.
Rollback restores the saved file and restarts the display manager.

On NixOS, remove those assignments from the declaration which generates the
session environment, rather than editing generated store-backed files. Build
and test the resulting generation first with `sudo nixos-rebuild test --flake
/etc/nixos`. Verify greeter and session driver selection, then make that tested
generation persistent through the normal update workflow. Retain the previous
generation and `/run/current-system` identity. Rollback uses the saved previous
generation; `sudo nixos-rebuild switch --rollback` applies when the changed
generation was made current. Local unmanaged files need their own preserved
backup and restoration.

Application fallback remains explicit and does not change the system default:

```sh
MESA_LOADER_DRIVER_OVERRIDE=zink GALLIUM_DRIVER=zink application
```

The test reservation, protected hardware services, source identity and rollback
remain the operator's responsibility. The image check is a source/configuration
policy check, not a GPU execution test.
