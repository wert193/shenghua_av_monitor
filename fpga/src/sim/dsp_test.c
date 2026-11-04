
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <math.h>
#define NTAPS 255
#define FADE 960
typedef struct {
    float banks[4][NTAPS], active[NTAPS], step[NTAPS];
    float history[2*NTAPS];
    int head, mode, remaining;
} Fir;
static int fir_init(Fir *f, const char *path) {
    *f = (Fir){0};
    FILE *fp = fopen(path, "rb");
    if (!fp) return -1;
    size_t n = fread(f->banks, sizeof(float), 3*NTAPS, fp);
    int extra = fgetc(fp); fclose(fp);
    if (n != 3*NTAPS || extra != EOF) return -1;
    for (int m=0; m<3; m++) for (int k=0; k<NTAPS; k++) {
        if (!isfinite(f->banks[m][k])) return -1;
    }
    // Delay the unfiltered reference to match the linear-phase FIR group delay.
    f->banks[3][(NTAPS-1)/2] = 1.0f;
    for (int k=0; k<NTAPS; k++) f->active[k] = f->banks[0][k];
    return 0;
}
static void fir_select(Fir *f, int mode) {
    if (mode < 0 || mode > 3 || mode == f->mode) return;
    f->mode = mode;
    f->remaining = FADE;
    // New transitions start from the CURRENT blend, including rapid re-presses.
    for (int k=0; k<NTAPS; k++)
        f->step[k] = (f->banks[mode][k] - f->active[k]) / FADE;
}
static float fir_tick(Fir *f, float input) {
    if (--f->head < 0) f->head = NTAPS-1;
    f->history[f->head] = f->history[f->head+NTAPS] = input;
    if (f->remaining) {
        for (int k=0; k<NTAPS; k++) f->active[k] += f->step[k];
        if (--f->remaining == 0)
            for (int k=0; k<NTAPS; k++) f->active[k] = f->banks[f->mode][k];
    }
    float y=0;
    for (int k=0; k<NTAPS; k++) y += f->active[k] * f->history[f->head+k];
    return y;
}

#ifdef DSP_TEST
// Portable executable to compare the actual DSP core to a numerical reference.
int main(int argc, char **argv) {
    if (argc != 5) return 2;
    Fir f; if (fir_init(&f, argv[1])) return 3;
    FILE *in=fopen(argv[2], "rb"), *modes=fopen(argv[3], "rb"), *out=fopen(argv[4], "wb");
    if (!in || !modes || !out) return 4;
    float x;
    while (fread(&x, sizeof x, 1, in) == 1) {
        int m=fgetc(modes); if (m==EOF) return 5;
        fir_select(&f,m); float y=fir_tick(&f,x);
        if (fwrite(&y,sizeof y,1,out)!=1) return 6;
    }
    fclose(in); fclose(modes); fclose(out); return 0;
}
#else
#include <fcntl.h>
#include <unistd.h>
#include <signal.h>
#include <sys/mman.h>
#include <sys/ioctl.h>
#include <sys/file.h>
#include <linux/i2c-dev.h>
#include <time.h>
#include <errno.h>
#include "pcm_source.h"
static volatile sig_atomic_t interrupted=0;
static void on_signal(int s) { (void)s; interrupted=1; }
static double now_s(void) {
    struct timespec t; clock_gettime(CLOCK_MONOTONIC,&t);
    return t.tv_sec+t.tv_nsec*1e-9;
}
static int wr(int fd, uint8_t reg, uint8_t val) {
    uint8_t b[3]={0x40,reg,val};
    return write(fd,b,3)==3 ? 0 : -1;
}
int main(int argc, char **argv) {
    if (argc!=6) return 2;
    Fir filter; if (fir_init(&filter,argv[4])) { fprintf(stderr,"Invalid coefficients\n"); return 2; }
    PcmSource song;
    if (pcm_load(&song,argv[5])) { fprintf(stderr,"Invalid song PCM\n"); return 2; }
    filter.mode=3;
    for (int k=0;k<NTAPS;k++) filter.active[k]=filter.banks[3][k];
    int rc=1, uio=-1, i2c=-1, owns_uio=0, codec_selected=0;
    volatile uint32_t *r=MAP_FAILED;
    size_t size=strtoul(argv[3],NULL,10);
    if (size<20 || size>1048576) { free(song.samples); return 2; }
    signal(SIGINT,on_signal); signal(SIGTERM,on_signal);
    int flags=fcntl(STDIN_FILENO,F_GETFL);
    if (flags<0 || fcntl(STDIN_FILENO,F_SETFL,flags|O_NONBLOCK)<0) { free(song.samples); return 2; }
    uio=open(argv[1],O_RDWR|O_CLOEXEC);
    if (uio<0 || flock(uio,LOCK_EX|LOCK_NB)) { perror("UIO open/lock"); goto cleanup; }
    owns_uio=1;
    r=mmap(NULL,size,PROT_READ|PROT_WRITE,MAP_SHARED,uio,0);
    if (r==MAP_FAILED) { perror("mmap"); goto cleanup; }
    i2c=open(argv[2],O_RDWR|O_CLOEXEC);
    if (i2c<0 || ioctl(i2c,I2C_SLAVE,0x3b)<0) { perror("I2C"); goto cleanup; }
    codec_selected=1;
    r[2]=r[3]=0;
    if (wr(i2c,0x23,(40<<2)|3) || wr(i2c,0x24,(40<<2)|3) ||
        wr(i2c,0x1c,0x21) || wr(i2c,0x1e,0x41)) { perror("Unmute"); goto cleanup; }
    unsigned emitted=0, clipped=0, slow_intervals=0;
    int stop_left=-1, stopped_by_request=0;
    double start=now_s(), last_heartbeat=start, last_poll=start;
    const unsigned limit=song.count+(NTAPS-1)/2;
    const double deadline=limit/48000.0*1.25+10.0;
    puts("Closer: PCM16 mono, 48kHz nominal, 255-tap LIVE ARM FIR, 20ms nominal crossfade.");
    puts("Mode=3 at sample=0"); fflush(stdout);
    for (unsigned n=0;n<limit;n++) {
        if ((n&255)==0) {
            double now=now_s();
            if (now-last_poll>0.020) slow_intervals++;
            last_poll=now;
            if (now-start>deadline) { fprintf(stderr,"Wall-clock deadline exceeded\n"); goto cleanup; }
            char cmds[64]; ssize_t count=read(STDIN_FILENO,cmds,sizeof cmds);
            if (count==0) interrupted=1;
            else if (count<0 && errno!=EAGAIN && errno!=EWOULDBLOCK && errno!=EINTR) interrupted=1;
            for (ssize_t k=0;k<count;k++) {
                if (cmds[k]=='h') last_heartbeat=now;
                else if (cmds[k]=='q') interrupted=1;
                else if (cmds[k]>='0' && cmds[k]<='3') {
                    int mode=cmds[k]-'0';
                    if (stop_left<0 && mode!=filter.mode) {
                        fir_select(&filter,mode);
                        printf("Mode=%d at sample=%u\n",mode,n); fflush(stdout);
                    }
                }
            }
            if (now-last_heartbeat>3.0) interrupted=1;
        }
        if (interrupted && stop_left<0) { stop_left=FADE; stopped_by_request=1; }
        // Equal input gain in every mode; no prefiltered recordings.
        float x=n<song.count ? song.samples[n]*(0.5f/32768.0f) : 0.0f;
        float y=fir_tick(&filter,x);
        float envelope=1.0f;
        if (n<2400) envelope=n/2400.0f;
        if (limit-n<=2400) envelope=(limit-1-n)/2400.0f;
        if (stop_left>=0) envelope*=stop_left/(float)FADE;
        y*=envelope;
        if (!isfinite(y)) { fprintf(stderr,"Nonfinite output\n"); goto cleanup; }
        if (y>0.95f || y< -0.95f) { clipped++; y=fmaxf(-0.95f,fminf(0.95f,y)); }
        int32_t pcm=(int32_t)lrintf(y*8388607.0f);
        unsigned spins=0;
        double wait_start=0;
        while (r[4]==0) {
            if ((++spins&1023)==0) {
                double now=now_s();
                if (!wait_start) wait_start=now;
                if (now-wait_start>0.25) { fprintf(stderr,"Sample clock timeout\n"); goto cleanup; }
            }
        }
        r[4]=1;
        r[2]=((uint32_t)pcm)&0xffffff; r[3]=((uint32_t)pcm)&0xffffff;
        emitted++;
        if (stop_left>=0 && --stop_left<0) break;
    }
    printf("Samples=%u wall_seconds=%.6f stop_requested=%d clipped=%u slow_256_sample_intervals=%u\n",
           emitted,now_s()-start,stopped_by_request,clipped,slow_intervals);
    puts("Timing diagnostics are not a hardware underrun counter. No FPGA FIR used.");
    rc=0;
cleanup:
    if (r!=MAP_FAILED) { r[2]=0; r[3]=0; }
    if (codec_selected) {
        int a=wr(i2c,0x1c,0x01), b=wr(i2c,0x1e,0x01);
        if (a || b) { fprintf(stderr,"Mute failed\n"); rc=1; }
    }
    if (i2c>=0) close(i2c);
    if (r!=MAP_FAILED) munmap((void *)r,size);
    if (owns_uio) flock(uio,LOCK_UN);
    if (uio>=0) close(uio);
    free(song.samples);
    return rc;
}
#endif
