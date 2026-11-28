/*
 * fprintd example to enroll right index finger
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
/* Test excerpts from fprintd v1.94.5 utils/enroll.c.
 * Source: https://gitlab.freedesktop.org/libfprint/fprintd/-/blob/v1.94.5/utils/enroll.c
 * Full upstream file SHA256: f882f90bd7e3b51182640d11c0ba92ae793b16b4d384286e9f754f464952d9c0
 * Only the functions below are copied; no implementation changes.
 */

static void
enroll_result (GObject *object, const char *result, gboolean done, void *user_data)
{
  FprintEnrollStatus *enroll_status = user_data;

  g_print ("Enroll result: %s\n", result);
  if (done != FALSE)
    {
      if (g_str_equal (result, "enroll-completed"))
        *enroll_status = ENROLL_COMPLETED;
      else
        *enroll_status = ENROLL_FAILED;
    }
}
