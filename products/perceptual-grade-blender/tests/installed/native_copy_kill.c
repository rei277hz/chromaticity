/* Test-only interruption inside Blender's RNA Image float-buffer memcpy.
 * Never shipped in the extension. Arming requires the exact numpy source and
 * length, so unrelated Blender/helper copies take the ordinary libc path. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <signal.h>
#include <stdatomic.h>
#include <stddef.h>
#include <stdint.h>
#include <unistd.h>

typedef void *(*copy_fn)(void *, const void *, size_t);
static copy_fn real_copy;
static const unsigned char *wanted_source, *old_values;
static size_t wanted_size, copied_size;
static int evidence_fd;
static _Atomic int armed;

static void *byte_copy(void *destination, const void *source, size_t size)
{
    volatile unsigned char *out = destination;
    const volatile unsigned char *in = source;
    for (size_t i = 0; i < size; ++i) out[i] = in[i];
    return destination;
}

__attribute__((constructor)) static void initialize(void)
{
    real_copy = (copy_fn)dlsym(RTLD_NEXT, "memcpy");
}

static int equal(const unsigned char *a, const unsigned char *b, size_t size)
{
    for (size_t i = 0; i < size; ++i) if (a[i] != b[i]) return 0;
    return 1;
}

int pg_copy_arm(const void *source, const void *before, size_t size,
                size_t prefix, int fd)
{
    if (!real_copy || !source || !before || !prefix || prefix >= size ||
        prefix % sizeof(float) || size % sizeof(float) || fd < 0 ||
        atomic_load_explicit(&armed, memory_order_acquire)) return 0;
    wanted_source = source;
    old_values = before;
    wanted_size = size;
    copied_size = prefix;
    evidence_fd = fd;
    atomic_store_explicit(&armed, 1, memory_order_release);
    return 1;
}

void *memcpy(void *destination, const void *source, size_t size)
{
    copy_fn copy = real_copy ? real_copy : byte_copy;
    if (!atomic_load_explicit(&armed, memory_order_acquire) ||
        source != wanted_source || size != wanted_size ||
        !atomic_exchange_explicit(&armed, 0, memory_order_acq_rel))
        return copy(destination, source, size);

    unsigned char *out = destination;
    const unsigned char *in = source;
    const int before_matches = equal(out, old_values, size);
    copy(destination, source, copied_size);
    /* Fixed native-endian uint64 record; no allocation/Python callbacks here. */
    const uint64_t evidence[] = {
        UINT64_C(0x5047434f50594b31), (uint64_t)getpid(), size, copied_size,
        before_matches, equal(out, in, copied_size),
        equal(out + copied_size, old_values + copied_size, size - copied_size),
        !equal(out, old_values, copied_size),
        !equal(out + copied_size, in + copied_size, size - copied_size),
    };
    if (write(evidence_fd, evidence, sizeof(evidence)) != sizeof(evidence)) _exit(91);
    /* The supervisor verifies the native evidence and sends SIGKILL. We never
     * return to foreach_set, invoke exception cleanup, or finish this copy. */
    raise(SIGSTOP);
    for (;;) pause();
}
