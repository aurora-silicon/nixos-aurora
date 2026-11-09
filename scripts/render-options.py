#!/usr/bin/env python3
"""Render the Aurora option metadata exported by checks.documentation."""
import json
from pathlib import Path
import sys


def expression(value):
    if isinstance(value, dict) and value.get('_type') == 'literalExpression':
        return value['text']
    return json.dumps(value, ensure_ascii=False)


def value_lines(label, value):
    text = expression(value)
    if '\n' in text or '`' in text:
        return [f'**{label}:**', '', '```nix', text, '```', '']
    return [f'**{label}:** `{text}`', '']


def render(options):
    if not options or any(not name.startswith('aurora.') for name in options):
        raise ValueError('expected the complete Aurora option namespace')
    lines = [
        '# Aurora options', '',
        'Generated from the module declarations. See [Modules](https://github.com/aurora-silicon/nixos-aurora/blob/main/docs/modules.md)',
        'for imports and behavior, and [Documentation](https://github.com/aurora-silicon/nixos-aurora/blob/main/docs/documentation.md) to regenerate this reference.', '',
        'This lists every public `aurora.*` option, including submodule fields. Standard NixOS and',
        'Apple Silicon options remain available; see the links in the module guide. For daemon settings,',
        '`null` preserves the program\'s default. Required fields apply only when their parent is configured.', '',
    ]
    for name, option in sorted(options.items()):
        description = option.get('description')
        declarations = option.get('declarations', [])
        if not description or not description.strip() or not declarations:
            raise ValueError(f'{name}: description and source declaration are required')
        lines.extend([f'## `{name}`', '', description.strip(), '', f'**Type:** {option["type"]}', ''])
        if 'default' in option:
            lines.extend(value_lines('Default', option['default']))
        else:
            lines.extend(['**Default:** required.', ''])
        if 'example' in option:
            lines.extend(value_lines('Example', option['example']))
        lines.extend(['**Declared in:** ' + ', '.join(
            f'[{url.rsplit("/", 1)[-1]}]({url})' for url in declarations), ''])
    return '\n'.join(lines)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('usage: render-options.py OPTIONS_JSON')
    print(render(json.loads(Path(sys.argv[1]).read_text())), end='')
