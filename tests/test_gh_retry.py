"""scripts/gh-retry: transient GitHub API failures are retried, others are not,
and a release left created by a failed create gets its files uploaded."""
import os
import pathlib
import stat
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "gh-retry"

FAKE = r"""#!/bin/bash
# a fake gh: plays the outcomes listed in $FAKE_PLAN (one per call: ok, 504, 404, exists), logs its arguments
n=$(cat "$FAKE_DIR/n" 2>/dev/null || echo 0); n=$((n + 1)); echo $n > "$FAKE_DIR/n"
echo "$*" >> "$FAKE_DIR/calls"
case "$1 $2" in "release view") [ -e "$FAKE_DIR/created" ] && { echo found; exit 0; } || { echo "release not found" >&2; exit 1; } ;; esac
what=$(sed -n "${n}p" "$FAKE_DIR/plan")
case $what in
  ok) [ "$1 $2" = "release create" ] && touch "$FAKE_DIR/created"; echo "out $n"; exit 0 ;;
  504) echo "HTTP 504: Gateway Timeout (https://api.github.com/repos/x/y/releases)" >&2; exit 1 ;;
  504created) touch "$FAKE_DIR/created"; echo "HTTP 504: Gateway Timeout" >&2; exit 1 ;;
  404) echo "HTTP 404: Not Found" >&2; exit 1 ;;
esac
"""


class GhRetry(unittest.TestCase):
    def run_with(self, plan, *args):
        d = tempfile.mkdtemp()
        os.makedirs(f"{d}/bin")
        gh = pathlib.Path(f"{d}/bin/gh")
        gh.write_text(FAKE)
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
        pathlib.Path(f"{d}/plan").write_text("\n".join(plan) + "\n")
        env = dict(os.environ, PATH=f"{d}/bin:" + os.environ["PATH"], FAKE_DIR=d, GH_RETRY_DELAY="0")
        r = subprocess.run([str(SCRIPT), *args], env=env, capture_output=True, text=True)
        calls = pathlib.Path(f"{d}/calls").read_text().splitlines() if os.path.exists(f"{d}/calls") else []
        return r, calls

    def test_a_504_is_retried(self):
        r, calls = self.run_with(["504", "504", "ok"], "api", "repos/x/y/releases", "--paginate")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, "out 3\n")
        self.assertEqual(len(calls), 3)

    def test_a_404_is_not_retried(self):
        r, calls = self.run_with(["404", "ok"], "api", "repos/x/y/releases/tags/t")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(len(calls), 1)

    def test_gives_up_after_the_attempts(self):
        r, calls = self.run_with(["504"] * 9, "api", "repos/x/y/releases")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(len(calls), 5)

    def test_release_view_of_a_missing_release_fails_at_once(self):
        r, calls = self.run_with([], "release", "view", "t1", "--repo", "x/y")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(len(calls), 1)

    def test_a_create_that_failed_after_creating_uploads_instead(self):
        r, calls = self.run_with(["504created", "x", "ok"], "release", "create", "t1", "a.rpm", "b.rpm",
                                 "--repo", "x/y", "--target", "abc", "--title", "T")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(calls[-1], "release upload t1 a.rpm b.rpm --repo x/y --clobber")


    def test_a_retried_download_overwrites(self):
        r, calls = self.run_with(["504", "ok"], "release", "download", "t1", "--repo", "x/y", "--dir", "d")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(calls[0], "release download t1 --repo x/y --dir d")
        self.assertEqual(calls[1], "release download t1 --repo x/y --dir d --clobber")


if __name__ == "__main__":
    unittest.main()
