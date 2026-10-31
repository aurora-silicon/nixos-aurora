# SPDX-License-Identifier: GPL-2.0-or-later
"""Compile fprintd's actual Aurora account gate against a fake passwd lookup."""

import re
import subprocess
import sys
import tempfile
from pathlib import Path


def function(source, name):
    match = re.search(r"^" + name + r" \(", source, re.M)
    if match is None:
        raise AssertionError(f"missing {name}")
    opening = source.index("{", match.start())
    depth, end = 1, opening + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return "static gboolean\n" + source[match.start():end]


HARNESS = r'''
#include <assert.h>
#include <pwd.h>
#include <stdbool.h>
#include <string.h>
#include <sys/types.h>
typedef int gboolean;

static int fake_getpwnam_r(const char *name, struct passwd *entry,
                           char *buffer, size_t length, struct passwd **found)
{
    (void)buffer; (void)length;
    if (strcmp(name, "missing") == 0) { *found = NULL; return 0; }
    if (strcmp(name, "lookup-error") == 0) { *found = NULL; return 5; }
    entry->pw_name = strcmp(name, "mismatch") == 0 ? "other" : (char *)name;
    entry->pw_uid = strcmp(name, "no-uid") == 0 ? (uid_t)-1 : (uid_t)1000;
    *found = entry;
    return 0;
}
#define getpwnam_r fake_getpwnam_r
FUNCTION
#undef getpwnam_r
int main(void)
{
    assert(aurora_account_resolves("existing"));
    assert(!aurora_account_resolves("missing"));
    assert(!aurora_account_resolves("lookup-error"));
    assert(!aurora_account_resolves("mismatch"));
    assert(!aurora_account_resolves("no-uid"));
    assert(!aurora_account_resolves(""));
    assert(!aurora_account_resolves(NULL));
    return 0;
}
'''


def main():
    source = Path(sys.argv[1]).read_text()
    code = HARNESS.replace("FUNCTION", function(source, "aurora_account_resolves"))
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)
        (path / "test.c").write_text(code)
        subprocess.run(["cc", "-std=c11", "-Wall", "-Werror", "test.c", "-o", "test"],
                       cwd=path, check=True)
        subprocess.run([str(path / "test")], check=True)


if __name__ == "__main__":
    main()
