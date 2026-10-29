#include "pcm_source.h"
int main(int argc,char **argv) {
    if (argc!=3) return 2;
    PcmSource s;
    if (pcm_load(&s,argv[1])) return 3;
    FILE *out=fopen(argv[2],"wb");
    if (!out) { free(s.samples); return 4; }
    for (unsigned n=0;n<s.count;n++) {
        uint16_t v=(uint16_t)s.samples[n];
        fputc(v&255,out); fputc(v>>8,out);
    }
    fclose(out); free(s.samples); return 0;
}
