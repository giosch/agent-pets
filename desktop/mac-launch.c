#include <mach-o/dyld.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* Finder and Terminal use the same installed command. The installer ships its own runtime. */
int main(int argc, char **argv) {
    char target[PATH_MAX];
#ifdef INSTALLER
    char self[PATH_MAX], resolved[PATH_MAX];
    uint32_t size = sizeof(self);
    if (_NSGetExecutablePath(self, &size) || !realpath(self, resolved)) return 1;
    char *slash = strrchr(resolved, '/');
    if (!slash) return 1;
    *slash = 0;
    if (snprintf(target, sizeof(target), "%s/../Resources/runtime/habitat-runtime", resolved) >= sizeof(target)) return 1;
    char **args = calloc((size_t)argc + 2, sizeof(char*));
    if (!args) return 1;
    args[0] = target; args[1] = "desktop-install";
    for (int i = 1; i < argc; i++) args[i+1] = argv[i];
    execv(target, args);
#else
    const char *home = getenv("HOME");
    if (!home || snprintf(target, sizeof(target), "%s/Library/Application Support/AgentPetsDesktop/agent-pets", home) >= sizeof(target)) return 1;
    execv(target, argv);
#endif
    perror("Agent Pets");
    return 1;
}
