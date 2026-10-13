// Verifies the reverse-engineered ED-AIC3000 liquid-lens protocol against the vendor library.
//
// Raw I2C reads/writes of register 0x0000 on device 0x18 are cross-checked with
// EDATEC's own getLiquid()/setLiquid(), in both directions; the original code is
// restored at the end.
//
// Build on the camera (needs EDATEC's ed-aic3x00-lib installed):
//   g++ -O2 -DENABLE_LIQUID lens_probe.cpp -leda_io2 -o lens_probe
//   ./lens_probe            # read-only comparison
//   ./lens_probe 32000      # also write 32000 raw, check via vendor, restore via vendor
//
// Result on 2026-10-13: raw 32500 == vendor 32500; raw write 32000 -> vendor reads
// 32000; vendor setLiquid(32500) -> raw reads 32500; write ~675 us, read ~836 us.
#include <linux/i2c.h>
#include <linux/i2c-dev.h>
#include <sys/ioctl.h>
#include <fcntl.h>
#include <unistd.h>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include "eda/eda-io.h"

static const uint16_t ADDR = 0x18;

static int rawRead(int fd, uint16_t reg, uint8_t out[4])
{
    uint8_t r[2] = {uint8_t(reg >> 8), uint8_t(reg & 0xff)};
    i2c_msg m[2] = {{ADDR, 0, 2, r}, {ADDR, I2C_M_RD, 4, out}};
    i2c_rdwr_ioctl_data d = {m, 2};
    return ioctl(fd, I2C_RDWR, &d);
}

static int rawWrite(int fd, uint16_t reg, const uint8_t in[4])
{
    uint8_t b[6] = {uint8_t(reg >> 8), uint8_t(reg & 0xff), in[0], in[1], in[2], in[3]};
    i2c_msg m = {ADDR, 0, 6, b};
    i2c_rdwr_ioctl_data d = {&m, 1};
    return ioctl(fd, I2C_RDWR, &d);
}

int main(int argc, char** argv)
{
    int fd = open("/dev/i2c-1", O_RDWR);
    if (fd < 0) { perror("open /dev/i2c-1"); return 1; }

    uint8_t b[4] = {0};
    int rc = rawRead(fd, 0x0000, b);
    const int rawOrig = b[0] | (b[1] << 8);
    printf("raw  reg0x0000 rc=%d bytes=%02x %02x %02x %02x -> %d\n", rc, b[0], b[1], b[2], b[3], rawOrig);
    rc = rawRead(fd, 0x0028, b);
    printf("raw  reg0x0028 rc=%d bytes=%02x %02x %02x %02x\n", rc, b[0], b[1], b[2], b[3]);

    eda::EdaIo* e = eda::EdaIo::getInstance();   // no setup(): the lens calls don't need it
    const int vendorOrig = e->getLiquid();
    printf("vendor getLiquid() = %d\n", vendorOrig);

    if (argc > 1) {
        const int test = atoi(argv[1]);
        const uint8_t w[4] = {uint8_t(test & 0xff), uint8_t((test >> 8) & 0xff), 0, 0};
        auto t0 = std::chrono::steady_clock::now();
        rc = rawWrite(fd, 0x0000, w);
        auto t1 = std::chrono::steady_clock::now();
        usleep(5000);   // the register reflects a write 1.5-3 ms later
        printf("raw write %d rc=%d (%.0f us) -> vendor getLiquid() = %d\n", test, rc,
               std::chrono::duration<double, std::micro>(t1 - t0).count(), e->getLiquid());

        t0 = std::chrono::steady_clock::now();
        for (int i = 0; i < 50; ++i) rawRead(fd, 0x0000, b);
        t1 = std::chrono::steady_clock::now();
        printf("raw read avg %.0f us\n", std::chrono::duration<double, std::micro>(t1 - t0).count() / 50);

        const int vr = e->setLiquid(vendorOrig);
        usleep(5000);
        rawRead(fd, 0x0000, b);
        printf("vendor setLiquid(%d) rc=%d -> raw read %d\n", vendorOrig, vr, b[0] | (b[1] << 8));
    }
    close(fd);
    return 0;
}
