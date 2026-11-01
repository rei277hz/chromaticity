/* Compiled only for macOS preflight; does not link or modify Blender. */
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static volatile uintptr_t pg_freed;
__attribute__((noinline)) static void pg_canary_allocate(void) {
    void *p = malloc(7137);
    if (!p) exit(2);
    memset(p, 0x51, 7137);
    pg_freed = (uintptr_t)p;
    printf("PG_ALLOC_CANARY 0x%lx\n", (unsigned long)pg_freed);
    fflush(stdout);
    free(p);
}
int main(void) {
    pg_canary_allocate();
    /* A deliberate native fault checks automatic first-fault stopping. */
    raise(SIGSEGV);
    return 3;
}
