/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Copyright (C) 2026 Ryan Murray */
/* Exercise the script plugin's private lifecycle with real keyboards and
 * native caps-lock queries. No renderer or console is required.
 */
#include "config.h"
#include "plugin.c"
#include "ply-keyboard.c"

#define CHECK(condition) do { \
        if (!(condition)) { \
                fprintf (stderr, "%s:%d: %s\n", __FILE__, __LINE__, #condition); \
                exit (EXIT_FAILURE); \
        } \
} while (0)

int
main (int argc, char **argv)
{
        ply_boot_splash_plugin_t *plugin;
        ply_keyboard_t *first, *second;
        ply_terminal_t *terminal = ply_terminal_new ("/dev/null", NULL);

        CHECK (argc == 2);
        plugin = calloc (1, sizeof *plugin);
        plugin->loop = ply_event_loop_get_default ();
        plugin->displays = ply_list_new ();
        plugin->script_env_vars = ply_list_new ();
        plugin->script_filename = strdup (argv[1]);
        plugin->image_dir = strdup ("/");

        /* Starting without a keyboard must make caps-lock false. */
        CHECK (start_animation (plugin));
        CHECK (plugin->script_plymouth_lib->keyboard == NULL);
        first = ply_keyboard_new_for_terminal (terminal);
        second = ply_keyboard_new_for_terminal (terminal);
        set_keyboard (plugin, first);
        CHECK (ply_list_get_length (first->keyboard_input_handler_list) == 1);
        on_timeout (plugin);
        set_keyboard (plugin, second);
        CHECK (ply_list_get_length (first->keyboard_input_handler_list) == 0);
        CHECK (ply_list_get_length (second->keyboard_input_handler_list) == 1);
        unset_keyboard (plugin, first);
        ply_keyboard_free (first);
        on_timeout (plugin);
        CHECK (plugin->keyboard == second);
        CHECK (plugin->script_plymouth_lib->keyboard == second);

        /* Hide/show must retain selection and re-register the input handler. */
        stop_animation (plugin);
        CHECK (ply_list_get_length (second->keyboard_input_handler_list) == 0);
        CHECK (plugin->keyboard == second);
        CHECK (plugin->script_plymouth_lib == NULL);
        CHECK (start_animation (plugin));
        CHECK (ply_list_get_length (second->keyboard_input_handler_list) == 1);
        on_timeout (plugin);
        unset_keyboard (plugin, second);
        CHECK (ply_list_get_length (second->keyboard_input_handler_list) == 0);
        ply_keyboard_free (second);
        on_timeout (plugin);
        CHECK (plugin->script_plymouth_lib->keyboard == NULL);
        stop_animation (plugin);
        destroy_plugin (plugin);
        ply_terminal_free (terminal);
        puts ("script keyboard attach, replace, detach, and hide/show passed");
        return EXIT_SUCCESS;
}
