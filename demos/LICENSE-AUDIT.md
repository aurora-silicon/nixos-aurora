# Public sources and models

No Apple code, model, firmware or compiled program is used by these demo recipes.
Source archives and revisions are in [sources.json](sources.json). Model URLs,
size limits and SHA-256 identities are in [models.json](models.json).

| Input | Public source and licence | Use and redistribution |
| --- | --- | --- |
| Capture filter and RNNoise serializer | [capture-ns f843fd3](https://github.com/aurora-silicon/capture-ns/tree/f843fd3d053f716222caa7286a2095a9ffb8e762), MIT | Filter plugin, launcher, unmodified serializer and dependency lock. Preserve its MIT notice. |
| libane userspace | [omarchy-ane 1adf2ee](https://github.com/aurora-silicon/omarchy-ane/tree/1adf2ee392ef7d3d64a24743d293dbc1670f0e8b/libane), MIT | Static userspace library linked into capture and Whisper. The checked-in source-only archive contains just its C/headers, Makefile, UAPI header and licence. Every text file is independently hash-pinned; rebuild with `python3 demos/rebuild-libane-source.py`. No compiled fixtures or firmware are packaged. Kernel code is not linked. |
| RNNoise code and built-in arrays | [RNNoise v0.1.1](https://github.com/xiph/rnnoise/tree/6cbfd53eb348a8d394e0757b4025c6ded34eb2b6), BSD-3-Clause under COPYING | Pinned private library. Its built-in weight arrays are redistributed, as permitted by COPYING. Preserve individual source notices too. |
| Serialized RNNoise model | [rnn_data.c](https://raw.githubusercontent.com/xiph/rnnoise/6cbfd53eb348a8d394e0757b4025c6ded34eb2b6/src/rnn_data.c), BSD-3-Clause | Download source arrays on first run, verify SHA-256, serialize losslessly and verify the resulting SHA-256. No serialized weights in packages. |
| libDF implementation | [DeepFilterNet d375b2d](https://github.com/Rikorose/DeepFilterNet/tree/d375b2d8309e0935d165700c91da9de862a99c31), MIT OR Apache-2.0 | Pinned C API and recorded Cargo.lock, Tract 0.21.4. Remove the capi-to-default-model feature edge; no embedded DF3 archive. Dependency licences remain their own. |
| DeepFilterNet3 weights | [DF3 archive](https://raw.githubusercontent.com/Rikorose/DeepFilterNet/d375b2d8309e0935d165700c91da9de862a99c31/models/DeepFilterNet3_onnx.tar.gz), repository MIT/Apache-2.0 grant | No separate weight restriction was found in the capture integration's audit. This relies on the repository grant, not a separate model-card licence. Download and hash-check on first run. Not redistributed in binary packages. The public source archive contains the original models, used only for synthetic build checks. |
| Whisper implementation | [Aurora fork e65f3c4](https://github.com/aurora-silicon/whisper.cpp/tree/e65f3c4423baae5898e40458d8cb1d192897172e), MIT | File CLI, Vulkan backend, Linux libane adapter and worker. No Core ML or SDL recording backend. |
| Whisper tiny.en GGML weights | [immutable model file](https://huggingface.co/ggerganov/whisper.cpp/resolve/5359861c739e955e79d9a303bcbc70fb988958b1/ggml-tiny.en.bin), [MIT model card](https://huggingface.co/ggerganov/whisper.cpp/tree/5359861c739e955e79d9a303bcbc70fb988958b1) | First-run download only. SHA-256 is the published LFS object identity, also checked against the downloaded bytes during validation. MIT permits redistribution; these binary packages do not include it. |

The runtime models are public original weights, not Apple-compiled encoders.
ANE execution additionally needs a locally compiled open encoder bundle and the
compiler/runtime named by Whisper's worker. A present manifest alone does not
prove model parity; the worker validates it and reports any CPU fallback.
No complete native capture model is advertised by this revision.

Source for aurora-try and the camera effects update must be publicly fetchable
before those pins can be added here. The existing camera package is retained,
with its original source pin, and changed to opt-in.
