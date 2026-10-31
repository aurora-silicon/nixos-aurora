#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Serialize the audited RNNoise weights in its documented v1 model format."""
import argparse
import hashlib
from pathlib import Path
import re

SOURCE_SHA = "7b90ed18f065a34597d80b4c00e140a7c5eb6380ef8c9c6bf265384c944ae708"


def export(source):
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA:
        raise ValueError("expected rnn_data.c from RNNoise v0.1.1")
    text = source.decode()
    arrays = {}
    for name, count, values in re.findall(r"static const rnn_weight\s+(\w+)\[(\d+)\]\s*=\s*\{([^}]+)\}", text):
        numbers = [int(n) for n in re.findall(r"-?\d+", values)]
        if len(numbers) != int(count) or any(n < -128 or n > 127 for n in numbers):
            raise ValueError("invalid RNNoise weights")
        arrays[name] = numbers
    lines = ["rnnoise-nu model file version 1"]
    activations = {"TANH": 0, "SIGMOID": 1, "RELU": 2}
    for kind, name in (("Dense", "input_dense"), ("GRU", "vad_gru"), ("GRU", "noise_gru"),
                       ("GRU", "denoise_gru"), ("Dense", "denoise_output"), ("Dense", "vad_output")):
        match = re.search(r"static const " + kind + r"Layer\s+" + name + r"\s*=\s*\{([^}]+)\}", text)
        if not match:
            raise ValueError("missing RNNoise layer")
        fields = [f.strip() for f in match[1].split(",")]
        I, H = map(int, fields[-3:-1])
        activation = activations[fields[-1].removeprefix("ACTIVATION_")]
        lines.append(f"{I} {H} {activation}")
        # C structs store bias first; the model format stores bias last.
        for array in fields[1:-3] + fields[:1]:
            lines.append(" ".join(map(str, arrays[array])))
    return ("\n".join(lines) + "\n").encode()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    data = export(a.source.read_bytes())
    a.output.write_bytes(data)
    print(hashlib.sha256(data).hexdigest(), a.output.name)


if __name__ == "__main__":
    main()
