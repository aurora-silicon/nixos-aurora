/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Copyright (C) 2026 Ryan Murray */

#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <termios.h>
#include <unistd.h>

#include "ply-buffer.h"
#include "ply-terminal.h"
#include "ply-keyboard.h"

#define CHECK(expression) \
        do { \
                if (!(expression)) { \
                        fprintf (stderr, "%s:%d: %s: %s\n", __FILE__, __LINE__, #expression, strerror (errno)); \
                        return EXIT_FAILURE; \
                } \
        } while (0)

typedef struct
{
        bool received;
        bool timed_out;
        ply_event_loop_t *loop;
} input_context_t;

static void
on_keyboard_input (input_context_t *context,
                   const char      *input,
                   size_t           size)
{
        context->received = size == 1 && input[0] == 'q';
}

static void
on_timeout (input_context_t *context,
            ply_event_loop_t *loop)
{
        (void) loop;
        context->timed_out = true;
}

int
main (void)
{
        ply_terminal_t *terminal;
        ply_keyboard_t *keyboard;
        input_context_t context;
        ply_buffer_t *buffer;
        struct termios attributes;
        struct termios unlocked_attributes = { 0 };
        struct pollfd poll_fd;
        char byte;
        int master_fd, input_fd, output_fd;

        master_fd = posix_openpt (O_RDWR | O_NOCTTY | O_CLOEXEC);
        CHECK (master_fd >= 0);
        CHECK (grantpt (master_fd) == 0);
        CHECK (unlockpt (master_fd) == 0);
        terminal = ply_terminal_new (ptsname (master_fd), NULL);
        CHECK (ply_terminal_open (terminal));
        input_fd = ply_terminal_get_input_fd (terminal);
        output_fd = ply_terminal_get_fd (terminal);

        CHECK (input_fd >= 0 && output_fd >= 0 && input_fd != output_fd);
        CHECK ((fcntl (input_fd, F_GETFL) & O_NONBLOCK) != 0);
        CHECK ((fcntl (output_fd, F_GETFL) & O_NONBLOCK) == 0);
        CHECK (read (input_fd, &byte, 1) == -1 && errno == EAGAIN);

        /* Readiness can go stale if another reader consumes the data. */
        CHECK (write (master_fd, "x", 1) == 1);
        poll_fd = (struct pollfd) { .fd = input_fd, .events = POLLIN };
        CHECK (poll (&poll_fd, 1, 1000) == 1 && (poll_fd.revents & POLLIN));
        CHECK (read (output_fd, &byte, 1) == 1 && byte == 'x');
        CHECK (read (input_fd, &byte, 1) == -1 && errno == EAGAIN);

        /* A privileged console owner can unlock and reset termios after
         * readiness was reported. No complete canonical line remains.
         */
        CHECK (write (master_fd, "y", 1) == 1);
        CHECK (poll (&poll_fd, 1, 1000) == 1 && (poll_fd.revents & POLLIN));
        /* Non-root callers cannot lock termios, so unlocking is best effort. */
        ioctl (output_fd, TIOCSLCKTRMIOS, &unlocked_attributes);
        CHECK (tcgetattr (output_fd, &attributes) == 0);
        attributes.c_lflag |= ICANON;
        CHECK (tcsetattr (output_fd, TCSAFLUSH, &attributes) == 0);
        CHECK (read (input_fd, &byte, 1) == -1 && errno == EAGAIN);
        CHECK (write (master_fd, "z", 1) == 1);
        CHECK (read (input_fd, &byte, 1) == -1 && errno == EAGAIN);
        CHECK (write (master_fd, "\n", 1) == 1);
        CHECK (poll (&poll_fd, 1, 1000) == 1 && (poll_fd.revents & POLLIN));
        buffer = ply_buffer_new ();
        ply_buffer_append_from_fd (buffer, input_fd);
        CHECK (ply_buffer_get_size (buffer) == 2);
        CHECK (memcmp (ply_buffer_get_bytes (buffer), "z\n", 2) == 0);
        ply_buffer_append_from_fd (buffer, input_fd);
        CHECK (ply_buffer_get_size (buffer) == 2);
        ply_buffer_free (buffer);

        /* Close and reopen must recreate both independent descriptions. */
        ply_terminal_close (terminal);
        CHECK (fcntl (input_fd, F_GETFD) == -1 && errno == EBADF);
        CHECK (fcntl (output_fd, F_GETFD) == -1 && errno == EBADF);
        CHECK (ply_terminal_get_input_fd (terminal) == -1);
        CHECK (ply_terminal_open (terminal));
        CHECK ((fcntl (ply_terminal_get_input_fd (terminal), F_GETFL) & O_NONBLOCK) != 0);
        CHECK ((fcntl (ply_terminal_get_fd (terminal), F_GETFL) & O_NONBLOCK) == 0);
        /* Exercise the registered input watch and the real keyboard reader. */
        context = (input_context_t) { .loop = ply_event_loop_get_default () };
        keyboard = ply_keyboard_new_for_terminal (terminal);
        ply_keyboard_add_input_handler (keyboard,
                                         (ply_keyboard_input_handler_t) on_keyboard_input,
                                         &context);
        CHECK (ply_keyboard_watch_for_input (keyboard));
        CHECK (write (master_fd, "q", 1) == 1);
        ply_event_loop_watch_for_timeout (context.loop, 1.0,
                                          (ply_event_loop_timeout_handler_t) on_timeout,
                                          &context);
        /* run() frees all event sources on exit. Dispatch individual
         * iterations so the terminal can remove its watch during cleanup.
         */
        while (!context.received && !context.timed_out)
                ply_event_loop_process_pending_events (context.loop);
        CHECK (context.received && !context.timed_out);
        ply_event_loop_stop_watching_for_timeout (context.loop,
                                                  (ply_event_loop_timeout_handler_t) on_timeout,
                                                  &context);
        ply_keyboard_free (keyboard);
        ply_terminal_free (terminal);
        close (master_fd);
        return EXIT_SUCCESS;
}
