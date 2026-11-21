"""The NixOS Edge channel: the ref `channel-edge`.

`channel-edge` names a main commit whose Edge kernel and Mesa pins
(`kernel-aurora-edge`, `mesa-aurora-edge` in sources.json) are the
aurora-edge pair of the adopted aurora-distributions Edge train, and whose
outputs are in the signed cache. It moves only when that train is adopted.
"""
FEED = 'github:aurora-silicon/nixos-aurora/channel-edge'
PINS = {'linux': 'kernel-aurora-edge', 'mesa': 'mesa-aurora-edge'}


def edge_pair(sources):
    """The pair a commit's Edge pins package: {linux: revision, mesa: revision}."""
    return {name: (sources.get(pin) or {}).get('commit') for name, pin in PINS.items()}


def edge_gate(record, commit, sources):
    entry = ((record or {}).get('distributions') or {}).get('nixos') or {}
    if (not record or record.get('schema_version') != 1
            or entry.get('repository') != 'aurora-silicon/nixos-aurora' or entry.get('snapshot') != commit):
        raise ValueError(f'{commit} is not the NixOS commit of the adopted Edge train')
    pair = record.get('pair') or {}
    if edge_pair(sources) != {name: (pair.get(name) or {}).get('revision') for name in PINS}:
        raise ValueError(f'{commit} pins another Edge Linux/Mesa pair than the adopted Edge train')
