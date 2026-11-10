# SPDX-License-Identifier: MIT
"""Compile the driver's lockout-reason path with a fake ioctl and check that
each kernel reason becomes its own libfprint error, and that the driver says
before a prompt whether Touch ID needs the password."""
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def function(source, name):
    match = re.search(r'^' + name + r' \(', source, re.M)
    if match is None:
        raise AssertionError(f'missing {name}')
    opening = source.index('{', match.start())
    depth, end = 1, opening + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[match.start():end]


def block(source, first, last):
    start = source.index(first)
    return source[start:source.index(last, start) + len(last)]


HARNESS = r'''
#include <assert.h>
#include <errno.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
typedef uint32_t guint32;
typedef char gchar;
typedef struct { int domain; int code; char message[256]; } GError;
typedef struct { int fd; } FpiDeviceAurora;
typedef FpiDeviceAurora FpDevice;
typedef int gboolean;
#define TRUE 1
#define FALSE 0
#define FPI_DEVICE_AURORA(device) (device)
static void g_propagate_error (GError **dest, GError *src)
{
  if (dest)
    *dest = src;
}
enum {
  FP_DEVICE_ERROR_LOCKED_OUT = 0x102,
  FP_DEVICE_ERROR_PASSWORD_REQUIRED,
  FP_DEVICE_ERROR_PASSWORD_REQUIRED_AFTER_BOOT,
};
#define SEP_BIO_STATUS_LOCKOUT 8
#define fp_dbg(...) do { } while (0)
static GError last;
static GError *fpi_device_error_new_msg (int code, const char *fmt, ...)
{
  va_list ap;
  va_start (ap, fmt);
  last.code = code;
  vsnprintf (last.message, sizeof last.message, fmt, ap);
  va_end (ap);
  return &last;
}
static const gchar *aurora_status_reason (guint32 status)
{
  assert (status == SEP_BIO_STATUS_LOCKOUT);
  return "locked";
}
@STATE@
static int answer_errno;
static struct aurora_lockout_state answer;
static unsigned long asked;
#define ioctl fake_ioctl
static int fake_ioctl (int fd, unsigned long req, void *arg)
{
  assert (fd == 3);
  asked = req;
  if (answer_errno) { errno = answer_errno; return -1; }
  memcpy (arg, &answer, sizeof answer);
  return 0;
}
static GError *
@LOCKOUT@
static gboolean
@REQUIRED@
#undef ioctl
static int reason (int err, guint32 locked, guint32 flags)
{
  FpiDeviceAurora self = { 3 };
  answer_errno = err;
  answer = (struct aurora_lockout_state) { locked, 5, 0, flags };
  asked = 0;
  return aurora_lockout_new (&self, "verification")->code;
}
/* -1: not required; otherwise the reason's code */
static int required (int fd, int err, guint32 locked, guint32 flags)
{
  FpiDeviceAurora self = { fd };
  GError *why = NULL;
  answer_errno = err;
  answer = (struct aurora_lockout_state) { locked, 5, 0, flags };
  asked = 0;
  if (!aurora_password_required (&self, &why))
    {
      assert (why == NULL);
      return -1;
    }
  assert (why != NULL);
  assert (asked == AURORA_LOCKOUT_STATE);
  return why->code;
}
int main (void)
{
  _Static_assert (sizeof (struct aurora_lockout_state) == 16, "lockout ABI");
  _Static_assert (AURORA_LOCKOUT_STATE == _IOR (0xB1, 0x0e, struct aurora_lockout_state), "ioctl");
  /* Older kernels do not answer on /dev/sep-bio: the lockout, as before. */
  assert (reason (ENOTTY, 0, 0) == FP_DEVICE_ERROR_LOCKED_OUT);
  assert (asked == AURORA_LOCKOUT_STATE);
  /* No device: the lockout, without asking. */
  assert (aurora_lockout_new (NULL, "enrolment")->code == FP_DEVICE_ERROR_LOCKED_OUT);
  /* The wait after boot (flags as the kernel sets them, EVERY_PASSWORD = 1). */
  assert (reason (0, 1, 1 | AURORA_LOCKOUT_FLAG_AFTER_BOOT) ==
          FP_DEVICE_ERROR_PASSWORD_REQUIRED_AFTER_BOOT);
  /* The wait wins over a lockout: the first password ends both. */
  assert (reason (0, 1, 1 | AURORA_LOCKOUT_FLAG_AFTER_BOOT |
                        AURORA_LOCKOUT_FLAG_FAILED_ATTEMPTS) ==
          FP_DEVICE_ERROR_PASSWORD_REQUIRED_AFTER_BOOT);
  /* Five misses: the real lockout. */
  assert (reason (0, 1, 1 | AURORA_LOCKOUT_FLAG_FAILED_ATTEMPTS) ==
          FP_DEVICE_ERROR_LOCKED_OUT);
  assert (strstr (last.message, "too many failed attempts"));
  /* Locked for another reason, or re-armed meanwhile: the password, no blame. */
  assert (reason (0, 1, 1) == FP_DEVICE_ERROR_PASSWORD_REQUIRED);
  assert (reason (0, 0, 1) == FP_DEVICE_ERROR_PASSWORD_REQUIRED);

  /* Before a prompt: after boot the prompt goes straight to the password. */
  assert (required (3, 0, 1, 1 | AURORA_LOCKOUT_FLAG_AFTER_BOOT) ==
          FP_DEVICE_ERROR_PASSWORD_REQUIRED_AFTER_BOOT);
  assert (required (3, 0, 1, 1 | AURORA_LOCKOUT_FLAG_FAILED_ATTEMPTS) ==
          FP_DEVICE_ERROR_LOCKED_OUT);
  assert (required (3, 0, 1, 1) == FP_DEVICE_ERROR_PASSWORD_REQUIRED);
  /* Armed: the prompt asks for a finger. */
  assert (required (3, 0, 0, 1) == -1);
  assert (asked == AURORA_LOCKOUT_STATE);
  /* A kernel that cannot say: a finger, as before. */
  assert (required (3, ENOTTY, 0, 0) == -1);
  /* Not open: nothing asked. */
  assert (required (-1, 0, 1, 1 | AURORA_LOCKOUT_FLAG_AFTER_BOOT) == -1);
  assert (asked == 0);
  return 0;
}
'''


def main():
    source = Path(sys.argv[1]).read_text()
    state = block(source, 'struct aurora_lockout_state\n',
                  '#define AURORA_LOCKOUT_FLAG_FAILED_ATTEMPTS 4\n')
    code = (HARNESS.replace('@STATE@', state)
            .replace('@LOCKOUT@', function(source, 'aurora_lockout_new'))
            .replace('@REQUIRED@', function(source, 'aurora_password_required')))
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)
        (path / 'test.c').write_text(code)
        subprocess.run(['cc', '-std=gnu11', '-Wall', '-Werror', 'test.c', '-o', 'test'],
                       cwd=path, check=True)
        subprocess.run([str(path / 'test')], check=True)


if __name__ == '__main__':
    main()
