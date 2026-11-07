/* A real ARM64 entry verifies the native process before execing its child. */
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

int main(int argc, char **argv) {
    if (sysconf(_SC_PAGESIZE) != 4096) {
        fputs("Steam payload did not inherit 4 KiB pages\n", stderr);
        return 91;
    }
    const char *probe = getenv("AURORA_TEST_STEAM_PROBE");
    if (!probe || setenv("AURORA_TEST_PARENT_PAGES", "4096", 1)) return 92;
    char **child = calloc((size_t)argc + 2, sizeof(char *));
    if (!child) return 93;
    child[0] = "python3";
    child[1] = (char *)probe;
    for (int i = 1; i < argc; ++i) child[i + 1] = argv[i];
    execv("/usr/bin/python3", child);
    perror("exec Python descendant inside Steam FHS");
    return 94;
}
