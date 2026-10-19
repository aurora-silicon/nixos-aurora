import os
from pathlib import Path
import shlex
import subprocess
import tempfile

with tempfile.TemporaryDirectory() as directory:
    probe = Path(directory)/'modinfo'
    probe.write_text('#!' + os.environ['probeShell'] + '\nif [ "$AURORA_TEST_MODULE_RESULT" = absent ]; then exit 1; fi\nprintf "%s\\n" "$AURORA_TEST_MODULE_RESULT"\n')
    probe.chmod(0o755)
    for result, accepted in [('absent', False), ('(builtin)', False), ('', False),
            ('/lib/modules/7.2.10/apple_sep.ko', True),
            ('/lib/modules/7.2.10/apple_sep.ko.zst', True),
            ('/lib/modules/7.2.10/apple_sep.ko.xz', True),
            ('/lib/modules/7.2.10/apple_sep.ko.gz', True)]:
        value = subprocess.run(shlex.split(os.environ['sepCondition']), env={**os.environ,
            'PATH': directory+':'+os.environ['PATH'], 'AURORA_TEST_MODULE_RESULT': result})
        assert (value.returncode == 0) == accepted, (result, value.returncode)
        print(result or '<empty>', 'accepted' if accepted else 'skipped')
