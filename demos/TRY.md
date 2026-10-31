# Try the opt-in demos

Install the packages built from this branch. Nothing starts at installation,
no default camera or microphone changes, and no weights are fetched until a
model is requested. Run as your normal user.

| Distro | Packages |
| --- | --- |
| Fedora aarch64 | `aurora-models aurora-capture-ns aurora-rnnoise aurora-libdf whisper-cpp-aurora` |
| Arch Linux ARM | The same package names; build `aurora-capture-ns` once for all three capture packages. |
| NixOS aarch64 | Flake outputs `aurora-models`, `capture-ns`, `rnnoise`, `libdf`, `whisper-cpp-aurora`. Add packages to `environment.systemPackages` explicitly. No module enables these demos. |

## Transcribe a file

M1 Pro or M2, Fedora/ALARM/NixOS, with a mono 16 kHz WAV file you choose:

```sh
whisper.cpp-aurora --engine auto -f "$HOME/aurora-demo.wav"
```

The first run fetches and SHA-256-checks the MIT tiny.en model in
`$XDG_CACHE_HOME/aurora-models` (default `~/.cache/aurora-models`). Expect
`engine=gpu` with a hardware Vulkan driver, or `engine=cpu`. Text goes to the
terminal. This command reads the file; it never opens a microphone or speaker.
Use `--engine cpu` to compare. `--engine gpu` refuses if no hardware Vulkan
GPU is found. `--engine ane` requires your explicitly supplied
`WHISPER_ANE_ENCODER` open compiled bundle and its external compiler/runtime;
the native worker reports any CPU fallback. Auto prefers that bundle when
present, otherwise hardware Vulkan, otherwise CPU. Native failure follows
libane's upstream CPU fallback policy; it does not retry Vulkan mid-utterance.

Off: let the command finish or press **Ctrl-C**. There is no service or graph
to restore. The checked model cache remains for the next run.

## Choose a capture filter in the morning

M1 Pro or M2, any of the three distros. The lead first sets `AURORA_MIC_NODE`
to the exact existing microphone `node.name` from `pw-dump`; never use a sink
monitor or a default-source shortcut. This is a morning-only lead command:

```sh
aurora-capture-ns --engine cpu --model rnnoise --source "${AURORA_MIC_NODE:?set the explicit microphone node.name}"
```

Expect `engine=cpu` and a separate `Aurora Microphone (rnnoise)` source. Pick
that source in the recording application yourself. Use `--model df3` for
DeepFilterNet3. The first run downloads and verifies the selected weights.
No capture model runs on ANE or Vulkan in this revision; forced unsupported
engines fail clearly. The launcher never changes the system's default source.

Off: press **Ctrl-C** in the launch terminal. Its dedicated filter-chain client
exits and removes the virtual source. No persistent PipeWire configuration,
user service, playback route or UCM change needs undoing.

No microphone recording or audio playback was used for package validation.
Checks use synthetic buffers and public model data only.

## Camera and aurora-try

The existing camera package remains available, disabled by default. Its source
pin still predates the effects integration. Do not treat it as the new
blur/framing demo. Its explicit off command is:

```sh
systemctl --user disable --now aurora-camera-denoise.service
```

For an older ALARM package that globally enabled it, use
`systemctl --user mask --now aurora-camera-denoise.service` instead. Preserve
any intentional previous user selection when upgrading.

Aurora-try and the camera effects update still need public source archives.
No speculative launcher, model pin or unsupported camera command is installed.
See [PARITY.md](PARITY.md) for the remaining gaps.

## Device permissions

Recommend `TAG+="uaccess"` on ANE devices in the runtime's udev package, rather
than automatically adding users to `accel`. These consumer packages change
neither groups nor device rules. Logind seat ACLs do not grant headless SSH
sessions access by themselves; the lead must use the runtime's explicit
permission setup if testing ANE remotely. Permission failure is reported and
uses the supported fallback; it is never a presence or idle check.
