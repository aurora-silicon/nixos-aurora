/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Regression test: flush_head() dirties only the areas it copied. */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <xf86drm.h>
#include <xf86drmMode.h>

#define drmModeDirtyFB mock_dirty_fb
#define drmModeGetCrtc mock_get_crtc
#define drmModeFreeCrtc mock_free_crtc
#define drmSetClientCap mock_set_cap
#define drmModeSetCrtc mock_set_crtc

int mock_dirty_fb (int, uint32_t, drmModeClipPtr, uint32_t);
drmModeCrtcPtr mock_get_crtc (int, uint32_t);
void mock_free_crtc (drmModeCrtcPtr);
int mock_set_cap (int, uint64_t, uint64_t);
int mock_set_crtc (int, uint32_t, uint32_t, uint32_t, uint32_t, uint32_t *, int,
                   drmModeModeInfoPtr);

#include "src/plugins/renderers/drm/plugin.c"

#define W 640
#define H 400

static drmModeClip last_clips[MAX_FLUSH_CLIPS + 1];
static uint32_t last_num_clips;
static int dirty_calls;
static drmModeCrtc crtc = { .crtc_id = 20, .buffer_id = 30 };

int mock_dirty_fb (int fd, uint32_t buffer_id, drmModeClipPtr clips, uint32_t num_clips)
{
        assert (fd == 7 && buffer_id == 30);
        assert (num_clips >= 1 && num_clips <= MAX_FLUSH_CLIPS);
        memcpy (last_clips, clips, num_clips * sizeof (*clips));
        last_num_clips = num_clips;
        dirty_calls++;
        return 0;
}

drmModeCrtcPtr mock_get_crtc (int fd, uint32_t id)
{
        assert (fd == 7 && id == 20);
        return &crtc;
}

void mock_free_crtc (drmModeCrtcPtr c)
{
        assert (c == &crtc);
}

static int scanouts;

/* No atomic modesetting: the scan-out reset is a plain SetCrtc. */
int mock_set_cap (int fd, uint64_t cap, uint64_t value)
{
        (void) fd; (void) cap; (void) value;
        return -1;
}

int mock_set_crtc (int fd, uint32_t id, uint32_t buffer, uint32_t x, uint32_t y,
                   uint32_t *connectors, int count, drmModeModeInfoPtr mode)
{
        (void) connectors; (void) count; (void) mode;
        assert (fd == 7 && id == 20 && buffer == 30 && !x && !y);
        scanouts++;
        return 0;
}

static void fill (ply_renderer_head_t *head, long x, long y, unsigned long w, unsigned long h)
{
        ply_rectangle_t area = { .x = x, .y = y, .width = w, .height = h };

        ply_pixel_buffer_fill_with_hex_color (head->pixel_buffer, &area, 0xffffff);
}

/* Every pixel inside the reported clips, and the clips inside the buffer. */
static bool clips_cover (long x, long y, unsigned long w, unsigned long h)
{
        uint32_t i;
        long px, py;

        for (i = 0; i < last_num_clips; i++)
                assert (last_clips[i].x1 < last_clips[i].x2 && last_clips[i].x2 <= W &&
                        last_clips[i].y1 < last_clips[i].y2 && last_clips[i].y2 <= H);
        for (py = y; py < (long) (y + h); py++)
                for (px = x; px < (long) (x + w); px++) {
                        for (i = 0; i < last_num_clips; i++)
                                if (px >= last_clips[i].x1 && px < last_clips[i].x2 &&
                                    py >= last_clips[i].y1 && py < last_clips[i].y2)
                                        break;
                        if (i == last_num_clips)
                                return false;
                }
        return true;
}

static unsigned long clip_area (void)
{
        unsigned long sum = 0;
        uint32_t i;

        for (i = 0; i < last_num_clips; i++)
                sum += (unsigned long) (last_clips[i].x2 - last_clips[i].x1) *
                       (last_clips[i].y2 - last_clips[i].y1);
        return sum;
}

int main (void)
{
        ply_renderer_backend_t backend = { .device_fd = 7, .is_active = true,
                                           .requires_explicit_flushing = true };
        ply_renderer_buffer_t buffer = { .id = 30, .width = W, .height = H,
                                         .row_stride = W * 4 };
        ply_renderer_head_t head = { .controller_id = 20, .scan_out_buffer_id = 30,
                                     .area = { .width = W, .height = H },
                                     .row_stride = W * 4 };
        int i;

        buffer.map_address = calloc (H, W * 4);
        assert (buffer.map_address != NULL);
        backend.output_buffers = ply_hashtable_new (ply_hashtable_direct_hash,
                                                    ply_hashtable_direct_compare);
        ply_hashtable_insert (backend.output_buffers, (void *) (uintptr_t) 30, &buffer);
        head.backend = &backend;
        head.connector_ids = ply_array_new (PLY_ARRAY_ELEMENT_TYPE_UINT32);
        ply_array_add_uint32_element (head.connector_ids, 10);
        head.pixel_buffer = ply_pixel_buffer_new (W, H);
        ply_region_clear (ply_pixel_buffer_get_updated_areas (head.pixel_buffer));

        /* One small sprite: one clip around it, not the whole buffer. */
        fill (&head, 300, 180, 32, 32);
        flush_head (&backend, &head);
        assert (dirty_calls == 1 && last_num_clips == 1);
        assert (clips_cover (300, 180, 32, 32));
        assert (clip_area () == 32 * 32);
        assert (((uint32_t *) buffer.map_address)[190 * W + 310] == 0xffffffff);

        /* Two separate areas: both covered, far less than the buffer. */
        fill (&head, 10, 10, 20, 20);
        fill (&head, 500, 300, 40, 30);
        flush_head (&backend, &head);
        assert (dirty_calls == 2);
        assert (clips_cover (10, 10, 20, 20) && clips_cover (500, 300, 40, 30));
        assert (clip_area () < (unsigned long) W * H / 4);

        /* More areas than clips: merged, still covering every one. */
        for (i = 0; i < 40; i++)
                fill (&head, (i % 10) * 60 + 5, (i / 10) * 90 + 5, 8, 8);
        flush_head (&backend, &head);
        assert (dirty_calls == 3 && last_num_clips <= MAX_FLUSH_CLIPS);
        for (i = 0; i < 40; i++)
                assert (clips_cover ((i % 10) * 60 + 5, (i / 10) * 90 + 5, 8, 8));

        /* Nothing changed: nothing flushed. */
        flush_head (&backend, &head);
        assert (dirty_calls == 3);

        /* A scan-out buffer that has to be set again: the whole buffer. */
        crtc.buffer_id = 31;
        fill (&head, 300, 180, 4, 4);
        flush_head (&backend, &head);
        crtc.buffer_id = 30;
        assert (scanouts == 1 && dirty_calls == 4 && last_num_clips == 1);
        assert (last_clips[0].x1 == 0 && last_clips[0].y1 == 0 &&
                last_clips[0].x2 == W && last_clips[0].y2 == H);

        ply_array_free (head.connector_ids);
        ply_pixel_buffer_free (head.pixel_buffer);
        ply_hashtable_free (backend.output_buffers);
        free (buffer.map_address);
        puts ("PASS: dirty clips cover exactly the copied areas, merge past the limit, full buffer after a reset");
        return 0;
}
