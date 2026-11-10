# SPDX-License-Identifier: GPL-2.0-or-later
"""Compile the actual enrollment callback with a fake storage device.

No libfprint, D-Bus service or biometric hardware is needed. --aurora also
connects the real driver's ioctl error mapping to the callback.
"""
import argparse
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile


def function(source, name, result):
    match = re.search(r'^' + name + r' \(', source, re.M)
    if match is None:
        raise AssertionError(f'missing {name}')
    opening = source.index('{', match.start())
    depth, end = 1, opening + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return f'static {result}\n' + source[match.start():end]


HARNESS = r'''
#include <assert.h>
#include <errno.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
typedef int gboolean;
typedef int gint;
typedef struct { int domain, code; const char *message; } GError;
typedef struct { const char *driver; unsigned features; } FpDevice;
typedef struct { int unused; } FpPrint;
typedef struct { int unused; } GAsyncResult;
typedef struct { int unused; } GObject;
typedef struct { int fd; } FpiDeviceAurora;
typedef struct {
  FpDevice *dev;
  int enroll_data;
  void *current_cancellable;
} FprintDevicePrivate;
typedef struct { FprintDevicePrivate priv; } FprintDevice;
#define FALSE 0
#define TRUE 1
#define g_autoptr(type) type *
#define g_debug(...) ((void)0)
#define g_warning(...) ((void)0)
#define g_str_equal(a,b) (strcmp((a),(b)) == 0)
#define g_strcmp0(a,b) strcmp((a),(b))
#define g_strerror strerror
#define g_assert assert
#define FP_DEVICE_ERROR 100
#define FP_DEVICE_RETRY 101
#define G_IO_ERROR 102
#define G_IO_ERROR_CANCELLED 1
enum {
  FP_DEVICE_ERROR_GENERAL, FP_DEVICE_ERROR_NOT_SUPPORTED,
  FP_DEVICE_ERROR_NOT_OPEN, FP_DEVICE_ERROR_REMOVED,
  FP_DEVICE_ERROR_DATA_FULL, FP_DEVICE_ERROR_DATA_NOT_FOUND,
  FP_DEVICE_ERROR_DATA_INVALID, FP_DEVICE_ERROR_PROTO,
  FP_DEVICE_ERROR_TOO_HOT, FP_DEVICE_ERROR_DATA_DUPLICATE
};
enum {
  FP_DEVICE_RETRY_TOO_SHORT, FP_DEVICE_RETRY_CENTER_FINGER,
  FP_DEVICE_RETRY_REMOVE_FINGER, FP_DEVICE_RETRY_TOO_FAST
};
#define FP_DEVICE_FEATURE_STORAGE_LIST 1
#define FP_DEVICE_FEATURE_STORAGE_DELETE 2
#define SIGNAL_ENROLL_STATUS 0
static const int signals[] = {42};
static GError injected_error;
static GError *finish_error;
static FpPrint successful_print;
static FpPrint *finish_print;
static unsigned device_prints, host_prints;
static unsigned list_calls, delete_calls, retry_calls, completed, saved, emitted;
static int save_result, terminal;
static const char *status;
static const char *fp_device_get_driver(FpDevice *dev) { return dev->driver; }
static gboolean fp_device_has_feature(FpDevice *dev, unsigned feature)
{ return (dev->features & feature) != 0; }
static gboolean g_error_matches(GError *e, int domain, int code)
{ return e && e->domain == domain && e->code == code; }
static FprintDevicePrivate *fprint_device_get_instance_private(FprintDevice *rdev)
{ return &rdev->priv; }
static FpPrint *fp_device_enroll_finish(FpDevice *dev, GAsyncResult *res, GError **error)
{ (void)dev; (void)res; *error = finish_error; return finish_print; }
/* Model the dangerous operation: collect a device print missing from the host.
 * The callback must not even enter it for apple-sep. The control driver does. */
static gboolean try_delete_print(FprintDevice *rdev)
{
  unsigned unknown = device_prints & ~host_prints;
  (void)rdev;
  list_calls++;
  if (!unknown) return FALSE;
  device_prints &= ~(unknown & (0u - unknown));
  delete_calls++;
  return TRUE;
}
static FpPrint *fprint_device_create_enroll_template(FprintDevice *rdev, int finger)
{ (void)rdev; (void)finger; return &successful_print; }
static void enroll_progress_cb(void) {}
typedef void (*GAsyncReadyCallback)(FpDevice *, GAsyncResult *, void *);
static void fp_device_enroll(FpDevice *dev, FpPrint *print, void *cancel,
                            void (*progress)(void), void *data, void *destroy,
                            GAsyncReadyCallback callback, void *user)
{
  (void)dev; (void)print; (void)cancel; (void)progress; (void)data;
  (void)destroy; (void)callback; (void)user;
  retry_calls++;
}
static int print_data_save(FpPrint *print)
{ assert(print == &successful_print); saved++; return save_result; }
static struct { int (*print_data_save)(FpPrint *); } store = {print_data_save};
static void g_signal_emit(FprintDevice *rdev, int signal, int detail,
                          const char *name, gboolean done)
{ (void)rdev; (void)signal; (void)detail; emitted++; status = name; terminal = done; }
static void stoppable_action_completed(FprintDevice *rdev)
{ (void)rdev; completed++; }
@IOCTL@
@RESULT@
@CALLBACK@
@UTILS@
static void reset(int code)
{
  injected_error = (GError){FP_DEVICE_ERROR, code, "injected device error"};
  finish_error = &injected_error;
  finish_print = NULL;
  device_prints = 7; host_prints = 0;
  list_calls = delete_calls = retry_calls = completed = saved = emitted = 0;
  save_result = terminal = 0; status = NULL;
}
int main(void)
{
  FpDevice dev = {"apple-sep", 0};
  FprintDevice rdev = {{&dev, 0, NULL}};
  /* All three identities must survive, including every possible mix of prints
   * known to fprintd and unknown (for example enrolled by another OS). */
  for (unsigned features = 0; features < 4; features++) {
    dev.features = features;
    for (unsigned known = 0; known < 8; known++) {
      reset(FP_DEVICE_ERROR_DATA_FULL);
      host_prints = known;
      @INJECT_ENOSPC@
      enroll_cb(&dev, NULL, &rdev);
      assert(device_prints == 7 && host_prints == known);
      assert(list_calls == 0 && delete_calls == 0 && retry_calls == 0);
      assert(saved == 0 && emitted == 1 && terminal && completed == 1);
      assert(strcmp(status, "enroll-data-full") == 0);
    }
  }
  /* Positive control: the same DATA_FULL still collects an unknown print and
   * retries for other listing-capable drivers. This detects a vacuous fake. */
  dev.driver = "virtual_device_storage";
  for (unsigned features = 0; features < 4; features++) {
    reset(FP_DEVICE_ERROR_DATA_FULL);
    dev.features = features;
    host_prints = 6;
    enroll_cb(&dev, NULL, &rdev);
    if (features & FP_DEVICE_FEATURE_STORAGE_LIST) {
      assert(list_calls == 1 && delete_calls == 1 && retry_calls == 1);
      assert(device_prints == 6 && host_prints == 6);
      assert(emitted == 0 && completed == 0);
    } else {
      assert(list_calls == 0 && delete_calls == 0 && retry_calls == 0);
      assert(device_prints == 7 && terminal && completed == 1);
      assert(strcmp(status, "enroll-data-full") == 0);
    }
  }
  dev.driver = "apple-sep";
  reset(FP_DEVICE_ERROR_GENERAL);
  enroll_cb(&dev, NULL, &rdev);
  assert(strcmp(status, "enroll-unknown-error") == 0 && completed == 1);
  reset(FP_DEVICE_ERROR_GENERAL);
  finish_error = NULL; finish_print = &successful_print;
  enroll_cb(&dev, NULL, &rdev);
  assert(strcmp(status, "enroll-completed") == 0 && saved == 1 && terminal);
  reset(FP_DEVICE_ERROR_GENERAL);
  finish_error = NULL; finish_print = &successful_print; save_result = -ENOSPC;
  enroll_cb(&dev, NULL, &rdev);
  assert(strcmp(status, "enroll-failed") == 0 && saved == 1 && terminal);
  assert(delete_calls == 0 && retry_calls == 0);
  @TEST_UTILS@
  puts("PASS: capacity status, 32 SEP storage cases, other-driver controls, host save failure");
  return 0;
}
'''

IOCTL_STUBS = r'''
static int ioctl(int fd, unsigned long req, void *arg)
{ (void)fd; (void)req; (void)arg; errno = ENOSPC; return -1; }
static void g_set_error_literal(GError **error, int domain, int code, const char *message)
{ injected_error = (GError){domain, code, message}; *error = &injected_error; }
static void g_set_error(GError **error, int domain, int code, const char *format, ...)
{ g_set_error_literal(error, domain, code, format); }
'''

UTILS_STUBS = r'''
typedef enum { ENROLL_INCOMPLETE, ENROLL_COMPLETED, ENROLL_FAILED } FprintEnrollStatus;
static char output[512];
static void g_print(const char *format, ...)
{
  va_list args;
  va_start(args, format);
  vsnprintf(output + strlen(output), sizeof output - strlen(output), format, args);
  va_end(args);
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('device', type=Path)
    parser.add_argument('--aurora', type=Path)
    parser.add_argument('--enroll-utils', type=Path)
    args = parser.parse_args()
    source = args.device.read_text()
    code = HARNESS.replace('@RESULT@', function(source, 'enroll_result_to_name', 'const char *'))
    code = code.replace('@CALLBACK@', function(source, 'enroll_cb', 'void'))
    ioctl, inject, utils, test_utils = '', '', '', ''
    if args.aurora:
        ioctl = IOCTL_STUBS + function(args.aurora.read_text(), 'aurora_ioctl', 'gboolean')
        inject = '''FpiDeviceAurora sensor = {5};
      GError *error = NULL;
      assert(!aurora_ioctl(&sensor, 0, NULL, &error));
      assert(error->code == FP_DEVICE_ERROR_DATA_FULL);
      assert(strstr(error->message, "remove an enrolled fingerprint") != NULL);
      finish_error = error;'''
    if args.enroll_utils:
        utils = UTILS_STUBS + function(args.enroll_utils.read_text(), 'enroll_result', 'void')
        test_utils = '''FprintEnrollStatus state = ENROLL_INCOMPLETE;
  enroll_result(NULL, "enroll-data-full", TRUE, &state);
  assert(state == ENROLL_FAILED);
  assert(strstr(output, "Enroll result: enroll-data-full\\n"));
  assert(strstr(output, "Remove an enrolled fingerprint before trying again."));'''
    code = (code.replace('@IOCTL@', ioctl).replace('@INJECT_ENOSPC@', inject)
            .replace('@UTILS@', utils).replace('@TEST_UTILS@', test_utils))
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)
        (path / 'test.c').write_text(code)
        subprocess.run(shlex.split(os.environ.get('CC', 'cc')) +
                       ['-std=c11', '-Wall', '-Werror', 'test.c', '-o', 'test'],
                       cwd=path, check=True)
        subprocess.run([str(path / 'test')], check=True)


if __name__ == '__main__':
    main()
