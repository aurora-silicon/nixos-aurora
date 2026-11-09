/*
 * lsp-latency-check: check that LSP plugins report the latency they impose.
 *
 * Each case loads one LV2 plugin the way PipeWire's filter-graph does, runs it
 * in blocks of 1024 frames, then sends an impulse and finds where it comes out.
 * The plugin's latency port must equal that delay, both right after the first
 * run() and after a setting changes while it runs.  The loudness compensator
 * is checked at every FFT size in both modes.  The other plugins are the ones
 * the Asahi speaker graphs use, checked with their lookahead settings.
 *
 * Run with LV2_PATH pointing at the bundles to test.  Exit status 0 means
 * every case matched.
 *
 * SPDX-License-Identifier: LGPL-3.0-or-later
 */
#include <lilv/lilv.h>
#include <lv2/atom/atom.h>
#include <lv2/buf-size/buf-size.h>
#include <lv2/log/log.h>
#include <lv2/options/options.h>
#include <lv2/parameters/parameters.h>
#include <lv2/urid/urid.h>
#include <lv2/worker/worker.h>
#include <math.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define BLOCK 1024
#define LSP "http://lsp-plug.in/plugins/lv2/"

static char *uris[4096];
static int n_uris;

static LV2_URID map_uri(LV2_URID_Map_Handle h, const char *uri)
{
	for (int i = 0; i < n_uris; i++)
		if (strcmp(uris[i], uri) == 0)
			return i + 1;
	uris[n_uris] = strdup(uri);
	return ++n_uris;
}

static const char *unmap_uri(LV2_URID_Unmap_Handle h, LV2_URID id)
{
	return id > 0 && id <= (LV2_URID)n_uris ? uris[id - 1] : NULL;
}

static int log_vprintf(LV2_Log_Handle h, LV2_URID t, const char *f, va_list ap) { return 0; }
static int log_printf(LV2_Log_Handle h, LV2_URID t, const char *f, ...) { return 0; }
static LV2_Worker_Status schedule(LV2_Worker_Schedule_Handle h, uint32_t s, const void *d) { return LV2_WORKER_SUCCESS; }

static LilvWorld *world;

struct run {
	const LilvPlugin *p;
	LilvInstance *inst;
	uint32_t n_ports;
	float *ctrl;
	int latency_port;
	float *in[8], *out[8];
	int n_in, n_out;
	uint32_t audio_index[16];
};

static int set_control(struct run *r, const char *sym, float value)
{
	LilvNode *s = lilv_new_string(world, sym);
	const LilvPort *port = lilv_plugin_get_port_by_symbol(r->p, s);
	lilv_node_free(s);
	if (port == NULL)
		return -1;
	r->ctrl[lilv_port_get_index(r->p, port)] = value;
	return 0;
}

static int setup(struct run *r, const char *uri, double rate, const char **controls)
{
	static LV2_URID_Map map = { NULL, map_uri };
	static LV2_URID_Unmap unmap = { NULL, unmap_uri };
	static LV2_Log_Log lg = { NULL, log_printf, log_vprintf };
	static LV2_Worker_Schedule ws = { NULL, schedule };
	static const int32_t min_block = 1, max_block = 8192, seq_size = 32768, nominal = BLOCK;
	static float fr;
	static LV2_Options_Option opts[6];
	static LV2_Feature f_map = { LV2_URID__map, &map }, f_unmap = { LV2_URID__unmap, &unmap },
		f_log = { LV2_LOG__log, &lg }, f_ws = { LV2_WORKER__schedule, &ws },
		f_p2 = { LV2_BUF_SIZE__powerOf2BlockLength, NULL }, f_fixed = { LV2_BUF_SIZE__fixedBlockLength, NULL },
		f_bounded = { LV2_BUF_SIZE__boundedBlockLength, NULL }, f_opt = { LV2_OPTIONS__options, opts };
	const LV2_Feature *features[] = { &f_log, &f_map, &f_unmap, &f_p2, &f_fixed, &f_bounded, &f_opt, &f_ws, NULL };
	LV2_URID a_int = map_uri(NULL, LV2_ATOM__Int), a_float = map_uri(NULL, LV2_ATOM__Float);
	static LV2_Atom empty;

	fr = rate;
	opts[0] = (LV2_Options_Option){ LV2_OPTIONS_INSTANCE, 0, map_uri(NULL, LV2_BUF_SIZE__minBlockLength), sizeof(int32_t), a_int, &min_block };
	opts[1] = (LV2_Options_Option){ LV2_OPTIONS_INSTANCE, 0, map_uri(NULL, LV2_BUF_SIZE__maxBlockLength), sizeof(int32_t), a_int, &max_block };
	opts[2] = (LV2_Options_Option){ LV2_OPTIONS_INSTANCE, 0, map_uri(NULL, LV2_BUF_SIZE__sequenceSize), sizeof(int32_t), a_int, &seq_size };
	opts[3] = (LV2_Options_Option){ LV2_OPTIONS_INSTANCE, 0, map_uri(NULL, LV2_BUF_SIZE_PREFIX "nominalBlockLength"), sizeof(int32_t), a_int, &nominal };
	opts[4] = (LV2_Options_Option){ LV2_OPTIONS_INSTANCE, 0, map_uri(NULL, LV2_PARAMETERS__sampleRate), sizeof(float), a_float, &fr };
	opts[5] = (LV2_Options_Option){ LV2_OPTIONS_INSTANCE, 0, 0, 0, 0, NULL };

	memset(r, 0, sizeof(*r));
	LilvNode *u = lilv_new_uri(world, uri);
	r->p = lilv_plugins_get_by_uri(lilv_world_get_all_plugins(world), u);
	lilv_node_free(u);
	if (r->p == NULL) {
		printf("FAIL %s: plugin not found\n", uri);
		return -1;
	}
	r->inst = lilv_plugin_instantiate(r->p, rate, features);
	if (r->inst == NULL) {
		printf("FAIL %s: instantiate failed\n", uri);
		return -1;
	}
	r->n_ports = lilv_plugin_get_num_ports(r->p);
	r->ctrl = calloc(r->n_ports, sizeof(float));
	float *defs = calloc(r->n_ports, sizeof(float));
	lilv_plugin_get_port_ranges_float(r->p, NULL, NULL, defs);
	r->latency_port = lilv_plugin_has_latency(r->p) ? (int)lilv_plugin_get_latency_port_index(r->p) : -1;

	LilvNode *input = lilv_new_uri(world, LV2_CORE__InputPort), *audio = lilv_new_uri(world, LV2_CORE__AudioPort),
		*control = lilv_new_uri(world, LV2_CORE__ControlPort), *atom = lilv_new_uri(world, LV2_ATOM__AtomPort);
	for (uint32_t i = 0; i < r->n_ports; i++) {
		const LilvPort *port = lilv_plugin_get_port_by_index(r->p, i);
		if (lilv_port_is_a(r->p, port, atom)) {
			lilv_instance_connect_port(r->inst, i, &empty);
		} else if (lilv_port_is_a(r->p, port, audio)) {
			float *buf = calloc(BLOCK, sizeof(float));
			if (lilv_port_is_a(r->p, port, input))
				r->in[r->n_in++] = buf;
			else
				r->out[r->n_out++] = buf;
			lilv_instance_connect_port(r->inst, i, buf);
		} else if (lilv_port_is_a(r->p, port, control)) {
			r->ctrl[i] = isnan(defs[i]) ? 0.0f : defs[i];
			lilv_instance_connect_port(r->inst, i, &r->ctrl[i]);
		}
	}
	lilv_node_free(input); lilv_node_free(audio); lilv_node_free(control); lilv_node_free(atom);
	free(defs);

	for (const char **c = controls; c && *c; c += 2) {
		if (set_control(r, c[0], atof(c[1])) < 0) {
			printf("FAIL %s: no control %s\n", uri, c[0]);
			return -1;
		}
	}
	if (r->latency_port < 0 || r->n_in == 0 || r->n_out == 0) {
		printf("FAIL %s: no latency port or audio ports\n", uri);
		return -1;
	}
	lilv_instance_activate(r->inst);
	return 0;
}

static void teardown(struct run *r)
{
	lilv_instance_deactivate(r->inst);
	lilv_instance_free(r->inst);
	for (int i = 0; i < r->n_in; i++) free(r->in[i]);
	for (int i = 0; i < r->n_out; i++) free(r->out[i]);
	free(r->ctrl);
}

/* Run silence for settle frames, then an impulse, and return the frame at
 * which the first output peaks, counted from the impulse. */
static long measure(struct run *r, long settle, long window)
{
	long best_at = -1;
	float best = 0.0f;
	for (long done = 0; done < settle + window; done += BLOCK) {
		for (int c = 0; c < r->n_in; c++) {
			memset(r->in[c], 0, BLOCK * sizeof(float));
			if (done == settle)
				r->in[c][0] = 0.5f;
		}
		lilv_instance_run(r->inst, BLOCK);
		if (done < settle)
			continue;
		for (long n = 0; n < BLOCK; n++) {
			float v = fabsf(r->out[0][n]);
			if (v > best) {
				best = v;
				best_at = done - settle + n;
			}
		}
	}
	return best > 1e-4f ? best_at : -1;
}

static int failures, cases;

/* slack allows for filters whose impulse response peaks a little after the
 * pure delay, such as the multiband compressor's IIR crossover */
static void check(const char *what, struct run *r, long settle, long slack)
{
	long expected_max = 20000;
	long delay = measure(r, settle, expected_max + BLOCK);
	long reported = lrintf(r->ctrl[r->latency_port]);
	cases++;
	if (delay < 0 || labs(reported - delay) > slack) {
		failures++;
		printf("FAIL %s: reports %ld frames, delays %ld\n", what, reported, delay);
	} else {
		printf("ok   %s: reports %ld frames, delays %ld\n", what, reported, delay);
	}
}

int main(void)
{
	struct run r;
	char what[256], fft[8];
	const double rates[] = { 44100, 48000 };

	world = lilv_world_new();
	lilv_world_load_all(world);

	for (int ri = 0; ri < 2; ri++) {
		double rate = rates[ri];
		for (int mode = 0; mode <= 1; mode++) {
			for (int f = 0; f <= 6; f++) {
				snprintf(fft, sizeof(fft), "%d", f);
				const char *controls[] = { "enabled", "1", "input", "1", "mode", mode ? "1" : "0", "fft", fft, NULL };
				if (setup(&r, LSP "loud_comp_mono", rate, controls) < 0) {
					failures++;
					continue;
				}
				snprintf(what, sizeof(what), "loud_comp_mono %.0f Hz mode %d fft %d, first run", rate, mode, f);
				check(what, &r, BLOCK, 0);
				teardown(&r);
			}
		}
		/* change the FFT size while running: 1024, then 4096, then 256 */
		const char *start[] = { "enabled", "1", "input", "1", "mode", "0", "fft", "2", NULL };
		if (setup(&r, LSP "loud_comp_mono", rate, start) == 0) {
			snprintf(what, sizeof(what), "loud_comp_mono %.0f Hz fft 2 while running", rate);
			check(what, &r, 8 * BLOCK, 0);
			set_control(&r, "fft", 4);
			snprintf(what, sizeof(what), "loud_comp_mono %.0f Hz fft 2 -> 4 while running", rate);
			check(what, &r, 8 * BLOCK, 0);
			set_control(&r, "fft", 0);
			snprintf(what, sizeof(what), "loud_comp_mono %.0f Hz fft 4 -> 0 while running", rate);
			check(what, &r, 8 * BLOCK, 0);
			teardown(&r);
		} else {
			failures++;
		}
		const char *stereo[] = { "enabled", "1", "input", "1", "mode", "0", "fft", "2", NULL };
		if (setup(&r, LSP "loud_comp_stereo", rate, stereo) == 0) {
			snprintf(what, sizeof(what), "loud_comp_stereo %.0f Hz fft 2, first run", rate);
			check(what, &r, BLOCK, 0);
			teardown(&r);
		} else {
			failures++;
		}
		const char *comp[] = { "sla", "5", "al", "1", "at", "1", "rt", "100", "cr", "15", "kn", "0.5", NULL };
		if (setup(&r, LSP "compressor_stereo", rate, comp) == 0) {
			snprintf(what, sizeof(what), "compressor_stereo %.0f Hz lookahead 5 ms", rate);
			check(what, &r, 8 * BLOCK, 0);
			teardown(&r);
		} else {
			failures++;
		}
		const char *mb[] = { "mode", "0", "ce_0", "1", "sla_0", "5", "cbe_1", "1", "sf_1", "250", NULL };
		if (setup(&r, LSP "mb_compressor_stereo", rate, mb) == 0) {
			snprintf(what, sizeof(what), "mb_compressor_stereo %.0f Hz classic, lookahead 5 ms", rate);
			check(what, &r, 8 * BLOCK, 2);
			teardown(&r);
		} else {
			failures++;
		}
		const char *lim[] = { "th", "0.944", "lk", "5", "at", "1", "rt", "20", "alr", "0", "boost", "0", NULL };
		if (setup(&r, LSP "limiter_stereo", rate, lim) == 0) {
			snprintf(what, sizeof(what), "limiter_stereo %.0f Hz lookahead 5 ms", rate);
			check(what, &r, 8 * BLOCK, 0);
			teardown(&r);
		} else {
			failures++;
		}
	}
	printf("%d cases, %d failed\n", cases, failures);
	return failures == 0 && cases > 0 ? 0 : 1;
}
