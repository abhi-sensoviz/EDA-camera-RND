/*
 * Measures how long after an I2C write the ED-AIC3000 lens register reads back
 * the new focus code. Standalone: raw Linux i2c-dev, no vendor library.
 *
 *   gcc -O2 -Wall lens_latency.c -o lens_latency && ./lens_latency
 *
 * Writes 10 different codes three times (with 0 / 20 / 40 ms idle gaps), polls
 * the register after each write until it matches, prints the latency, and
 * restores the original code.
 *
 * Results on 2026-10-13 (two runs):
 *   min 1.47 ms, median 1.48 ms, max 3.14 ms; 3 of 30 first reads stale
 *   min 1.47 ms, median 1.48 ms, max 2.27 ms; 4 of 30 first reads stale
 * (a "stale" read still returned the previous code right after a write).
 */
#define _DEFAULT_SOURCE          /* usleep() and clock_gettime() from glibc */
#include <fcntl.h>
#include <linux/i2c.h>
#include <linux/i2c-dev.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>

#define ADDR 0x18

static int lens_write(int fd, int code)
{
    uint8_t b[6] = {0x00, 0x00, code & 0xFF, (code >> 8) & 0xFF, 0, 0};
    struct i2c_msg m = {.addr = ADDR, .flags = 0, .len = 6, .buf = b};
    struct i2c_rdwr_ioctl_data d = {.msgs = &m, .nmsgs = 1};
    return ioctl(fd, I2C_RDWR, &d) < 0 ? -1 : 0;
}

static int lens_read(int fd)
{
    uint8_t reg[2] = {0x00, 0x00}, v[4] = {0};
    struct i2c_msg m[2] = {
        {.addr = ADDR, .flags = 0,        .len = 2, .buf = reg},
        {.addr = ADDR, .flags = I2C_M_RD, .len = 4, .buf = v},
    };
    struct i2c_rdwr_ioctl_data d = {.msgs = m, .nmsgs = 2};
    if (ioctl(fd, I2C_RDWR, &d) < 0) return -1;
    return v[0] | (v[1] << 8);
}

static double now_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec * 1e3 + ts.tv_nsec / 1e6;
}

static int cmp(const void *a, const void *b)
{
    double x = *(const double *)a, y = *(const double *)b;
    return (x > y) - (x < y);
}

int main(void)
{
    int fd = open("/dev/i2c-1", O_RDWR | O_CLOEXEC);
    if (fd < 0) { perror("open /dev/i2c-1"); return 1; }

    const int orig = lens_read(fd);
    if (orig < 0) { perror("read lens"); return 1; }
    printf("original code %d\n", orig);

    const int targets[] = {20000, 30000, 21000, 29000, 25000, 25050, 25100, 40000, 10000, 32500};
    double lat[30];
    int n = 0, stale = 0, never = 0;

    for (int rep = 0; rep < 3; ++rep) {
        for (size_t i = 0; i < sizeof targets / sizeof *targets; ++i) {
            usleep(rep * 20000);                 /* idle gap 0 / 20 / 40 ms */
            const double t0 = now_ms();
            lens_write(fd, targets[i]);
            int reads = 0, v = -1;
            double ms = -1;
            while (now_ms() - t0 < 200) {
                v = lens_read(fd);
                ++reads;
                if (v == targets[i]) { ms = now_ms() - t0; break; }
            }
            if (ms < 0) ++never; else lat[n++] = ms;
            if (reads > 1) ++stale;
            printf("gap %2d ms  write %5d -> matched after %6.2f ms (%d reads)\n",
                   rep * 20, targets[i], ms, reads);
        }
    }
    qsort(lat, n, sizeof *lat, cmp);
    if (n)
        printf("latency min %.2f  median %.2f  max %.2f ms; stale first read %d/%d; never %d\n",
               lat[0], lat[n / 2], lat[n - 1], stale, n + never, never);

    lens_write(fd, orig);
    usleep(10000);
    printf("restored %d (orig %d)\n", lens_read(fd), orig);
    close(fd);
    return 0;
}
