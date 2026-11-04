/* Prepared little-endian, signed PCM16 mono, 48000 samples/s. */
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
typedef struct { int16_t *samples; unsigned count; } PcmSource;
static int pcm_load(PcmSource *source, const char *path) {
    *source = (PcmSource){0};
    FILE *file = fopen(path, "rb");
    if (!file) return -1;
    if (fseek(file, 0, SEEK_END)) { fclose(file); return -1; }
    long bytes = ftell(file);
    if (bytes < 2 || bytes % 2 || bytes > 48000L*600*2 || fseek(file, 0, SEEK_SET)) {
        fclose(file); return -1;
    }
    unsigned char *raw = malloc((size_t)bytes);
    if (!raw) { fclose(file); return -1; }
    if (fread(raw, 1, (size_t)bytes, file) != (size_t)bytes) {
        free(raw); fclose(file); return -1;
    }
    fclose(file);
    source->count = (unsigned)(bytes/2);
    source->samples = (int16_t *)raw;
    for (unsigned n=0; n<source->count; n++) {
        unsigned word = raw[2*n] | ((unsigned)raw[2*n+1] << 8);
        source->samples[n] = (int16_t)(word >= 32768 ? (int)word-65536 : (int)word);
    }
    return 0;
}
