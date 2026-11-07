/* Exercise the production DRM renderer with a simulated inherited HDR output.
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#include <assert.h>
#include <xf86drm.h>
#include <xf86drmMode.h>

#define drmSetClientCap mock_set_cap
#define drmModeObjectGetProperties mock_get_properties
#define drmModeGetProperty mock_get_property
#define drmModeFreeObjectProperties mock_free_properties
#define drmModeFreeProperty mock_free_property
#define drmModeAtomicAlloc mock_atomic_alloc
#define drmModeAtomicAddProperty mock_atomic_add
#define drmModeAtomicCommit mock_atomic_commit
#define drmModeAtomicFree mock_atomic_free
#define drmModeSetCrtc mock_set_crtc

int mock_set_cap (int, uint64_t, uint64_t);
drmModeObjectPropertiesPtr mock_get_properties (int, uint32_t, uint32_t);
drmModePropertyPtr mock_get_property (int, uint32_t);
void mock_free_properties (drmModeObjectPropertiesPtr);
void mock_free_property (drmModePropertyPtr);
drmModeAtomicReqPtr mock_atomic_alloc (void);
int mock_atomic_add (drmModeAtomicReqPtr, uint32_t, uint32_t, uint64_t);
int mock_atomic_commit (int, drmModeAtomicReqPtr, uint32_t, void *);
void mock_atomic_free (drmModeAtomicReqPtr);
int mock_set_crtc (int, uint32_t, uint32_t, uint32_t, uint32_t,
                   uint32_t *, int, drmModeModeInfoPtr);

#include "src/plugins/renderers/drm/plugin.c"

/* Properties 1/2 are HDR/colorspace; 3 is an unrelated writable property. */
static uint32_t property_ids[] = { 1, 2, 3 };
static uint64_t values[3][3];
static uint64_t pending[3][3];
static drmModePropertyRes property;
static drmModeObjectProperties properties;
static bool atomic_supported = true, atomic_enabled;
static bool no_properties, fail_alloc, fail_query, fail_property, fail_add, fail_commit;
static int commits, scanouts, allocations, queries;
static char request_token;

int mock_set_cap (int fd, uint64_t capability, uint64_t value)
{
        assert (fd == 7 && capability == DRM_CLIENT_CAP_ATOMIC);
        if (!atomic_supported)
                return -1;
        atomic_enabled = value;
        return 0;
}

drmModeObjectPropertiesPtr mock_get_properties (int fd, uint32_t id, uint32_t type)
{
        assert (fd == 7 && atomic_enabled && id >= 10 && id <= 12);
        assert (type == DRM_MODE_OBJECT_CONNECTOR);
        queries++;
        if (fail_query)
                return NULL;
        properties.count_props = no_properties ? 0 : 3;
        properties.props = property_ids;
        properties.prop_values = values[id - 10];
        return &properties;
}

drmModePropertyPtr mock_get_property (int fd, uint32_t id)
{
        assert (fd == 7 && id >= 1 && id <= 3);
        if (fail_property)
                return NULL;
        memset (&property, 0, sizeof property);
        property.prop_id = id;
        strcpy (property.name, id == 1 ? "HDR_OUTPUT_METADATA" :
                               id == 2 ? "Colorspace" : "link-status");
        return &property;
}

void mock_free_properties (drmModeObjectPropertiesPtr p) { assert (p == &properties); }
void mock_free_property (drmModePropertyPtr p) { assert (p == &property); }

drmModeAtomicReqPtr mock_atomic_alloc (void)
{
        if (fail_alloc)
                return NULL;
        allocations++;
        memcpy (pending, values, sizeof values);
        return (drmModeAtomicReqPtr) &request_token;
}

int mock_atomic_add (drmModeAtomicReqPtr r, uint32_t object, uint32_t prop, uint64_t value)
{
        assert (r == (drmModeAtomicReqPtr) &request_token);
        assert (object == 10 || object == 11); /* Never touch unrelated connector 12. */
        assert ((prop == 1 || prop == 2) && value == 0);
        if (fail_add)
                return -1;
        pending[object - 10][prop - 1] = value;
        return 0;
}

int mock_atomic_commit (int fd, drmModeAtomicReqPtr r, uint32_t flags, void *data)
{
        assert (fd == 7 && r == (drmModeAtomicReqPtr) &request_token && !data);
        assert (flags == DRM_MODE_ATOMIC_ALLOW_MODESET); /* Blocking, modeset allowed. */
        commits++;
        if (fail_commit)
                return -1;
        memcpy (values, pending, sizeof values);
        return 0;
}

void mock_atomic_free (drmModeAtomicReqPtr r)
{
        assert (r == (drmModeAtomicReqPtr) &request_token);
        allocations--;
}

int mock_set_crtc (int fd, uint32_t crtc, uint32_t buffer, uint32_t x, uint32_t y,
                   uint32_t *connectors, int count, drmModeModeInfoPtr mode)
{
        int i;
        (void) mode;
        assert (fd == 7 && crtc == 20 && buffer == 30 && !x && !y);
        assert (!atomic_enabled && allocations == 0);
        if (atomic_supported && !no_properties)
                for (i = 0; i < count; i++) {
                        assert (values[connectors[i] - 10][0] == 0);
                        assert (values[connectors[i] - 10][1] == 0);
                }
        scanouts++;
        return 0;
}

static void inherit_hdr (void)
{
        int i;
        for (i = 0; i < 3; i++) {
                values[i][0] = 123; /* Inherited metadata blob. */
                values[i][1] = 9;   /* BT2020_RGB UAPI enum. */
                values[i][2] = 42;
        }
        commits = scanouts = queries = 0;
}

static void check_failed_takeover (ply_renderer_backend_t *backend, ply_renderer_head_t *head)
{
        assert (!ply_renderer_head_set_scan_out_buffer (backend, head, 30));
        assert (scanouts == 0 && !atomic_enabled && allocations == 0);
        assert (values[0][0] == 123 && values[0][1] == 9);
}

int main (void)
{
        ply_renderer_backend_t backend = { .device_fd = 7 };
        ply_renderer_head_t head = { .controller_id = 20, .uses_hw_rotation = true };
        int i;
        head.connector_ids = ply_array_new (PLY_ARRAY_ELEMENT_TYPE_UINT32);
        ply_array_add_uint32_element (head.connector_ids, 10);
        ply_array_add_uint32_element (head.connector_ids, 11);

        /* Repeated HDR -> splash handoffs, including cloned outputs. */
        for (i = 0; i < 5; i++) {
                inherit_hdr ();
                assert (ply_renderer_head_set_scan_out_buffer (&backend, &head, 30));
                assert (commits == 1 && scanouts == 1 && queries == 2);
                assert (values[0][2] == 42 && values[1][2] == 42);
                assert (values[2][0] == 123 && values[2][1] == 9);
                assert (ply_renderer_head_set_scan_out_buffer (&backend, &head, 30));
                assert (commits == 1); /* SDR redraw: no redundant modeset. */
        }

        inherit_hdr (); fail_alloc = true; check_failed_takeover (&backend, &head); fail_alloc = false;
        fail_query = true; check_failed_takeover (&backend, &head); fail_query = false;
        fail_property = true; check_failed_takeover (&backend, &head); fail_property = false;
        fail_add = true; check_failed_takeover (&backend, &head); fail_add = false;
        fail_commit = true; check_failed_takeover (&backend, &head); fail_commit = false;
        assert (ply_renderer_head_set_scan_out_buffer (&backend, &head, 30)); /* Retry. */

        inherit_hdr (); no_properties = true;
        assert (ply_renderer_head_set_scan_out_buffer (&backend, &head, 30));
        assert (commits == 0); no_properties = false;
        inherit_hdr (); atomic_supported = false;
        assert (ply_renderer_head_set_scan_out_buffer (&backend, &head, 30));
        assert (commits == 0 && queries == 0);
        ply_array_free (head.connector_ids);
        puts ("PASS: inherited HDR reset before scanout, clone scope, SDR/legacy, failures and retry");
        return 0;
}
