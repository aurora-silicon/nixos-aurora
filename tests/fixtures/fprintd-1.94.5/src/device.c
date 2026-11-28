/*
 * /net/reactivated/Fprint/Device/foo object implementation
 * Copyright (C) 2008 Daniel Drake <dsd@gentoo.org>
 * Copyright (C) 2020 Marco Trevisan <marco.trevisan@canonical.com>
 *
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 2 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License along
 * with this program; if not, write to the Free Software Foundation, Inc.,
 * 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
 */
/* Test excerpts from fprintd v1.94.5 src/device.c.
 * Source: https://gitlab.freedesktop.org/libfprint/fprintd/-/blob/v1.94.5/src/device.c
 * Full upstream file SHA256: 4b0e878d726b70503123126e7bc7ccda9e1f2dc25f3c94235f8e9c77bd4901da
 * Only the functions below are copied; no implementation changes.
 */

static const char *
enroll_result_to_name (gboolean completed, gboolean enrolled, GError *error)
{
  if (!error)
    {
      if (!completed)
        return "enroll-stage-passed";
      else if (enrolled)
        return "enroll-completed";
      else
        return "enroll-failed";
    }

  if (error->domain == FP_DEVICE_RETRY)
    {
      switch (error->code)
        {
        case FP_DEVICE_RETRY_TOO_SHORT:
          return "enroll-swipe-too-short";

        case FP_DEVICE_RETRY_CENTER_FINGER:
          return "enroll-finger-not-centered";

        case FP_DEVICE_RETRY_REMOVE_FINGER:
          return "enroll-remove-and-retry";

        case FP_DEVICE_RETRY_TOO_FAST:
          return "enroll-too-fast";

        default:
          return "enroll-retry-scan";
        }
    }
  else
    {
      /* Which errors should be mapped to disconnection?
       * Are drivers/libfprint/fprintd really in agreement here?
       */
      if (g_error_matches (error, FP_DEVICE_ERROR, FP_DEVICE_ERROR_PROTO))
        return "enroll-disconnected";
      else if (g_error_matches (error, FP_DEVICE_ERROR, FP_DEVICE_ERROR_REMOVED))
        return "enroll-disconnected";
      else if (g_error_matches (error, FP_DEVICE_ERROR, FP_DEVICE_ERROR_TOO_HOT))
        return "enroll-disconnected";
      else if (g_error_matches (error, FP_DEVICE_ERROR, FP_DEVICE_ERROR_DATA_FULL))
        return "enroll-data-full";
      else if (g_error_matches (error, FP_DEVICE_ERROR, FP_DEVICE_ERROR_DATA_DUPLICATE))
        return "enroll-duplicate";
      else if (g_error_matches (error, G_IO_ERROR, G_IO_ERROR_CANCELLED))
        return "enroll-failed";

      return "enroll-unknown-error";
    }
}

static void
enroll_cb (FpDevice *dev, GAsyncResult *res, void *user_data)
{
  g_autoptr(GError) error = NULL;
  FprintDevice *rdev = user_data;
  FprintDevicePrivate *priv = fprint_device_get_instance_private (rdev);

  g_autoptr(FpPrint) print = NULL;
  const char *name;

  print = fp_device_enroll_finish (dev, res, &error);

  /* We need to special case the issue where the on device storage
   * is completely full. In that case, we check whether we can delete
   * a print that is not coming from us; assuming it is from an old
   * installation.
   * We do this synchronously, which is not great but should be good
   * enough. */
  if (g_error_matches (error, FP_DEVICE_ERROR, FP_DEVICE_ERROR_DATA_FULL))
    {
      g_debug ("Device storage is full");
      if (fp_device_has_feature (priv->dev, FP_DEVICE_FEATURE_STORAGE_LIST) &&
          try_delete_print (rdev))
        {
          /* Success? Then restart the operation */
          fp_device_enroll (priv->dev,
                            fprint_device_create_enroll_template (rdev, priv->enroll_data),
                            priv->current_cancellable,
                            enroll_progress_cb,
                            rdev,
                            NULL,
                            (GAsyncReadyCallback) enroll_cb,
                            rdev);
          return;
        }
    }

  name = enroll_result_to_name (TRUE, print != NULL, error);

  g_debug ("enroll_cb: result %s", name);

  if (print)
    {
      int r;
      r = store.print_data_save (print);
      if (r != 0)
        name = "enroll-failed";
    }

  g_signal_emit (rdev, signals[SIGNAL_ENROLL_STATUS], 0, name, TRUE);

  if (error && !g_error_matches (error, G_IO_ERROR, G_IO_ERROR_CANCELLED))
    g_warning ("Device reported an error during enroll: %s", error->message);

  stoppable_action_completed (rdev);
}
