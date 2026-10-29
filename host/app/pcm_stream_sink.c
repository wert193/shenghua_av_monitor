/*
 * Continuous PCM16 producer for the Shenghua 8192-sample playback FIFO.
 *
 * Unlike pcm_fifo_sink (a fixed-length song player), this process is meant to
 * run for a whole live-monitor session: it pre-fills the FIFO, starts the
 * hardware 48 kHz clock, then streams whatever the USB microphone path writes
 * to stdin.  It never stops at a fixed sample count.  Underruns are counted
 * by hardware; this program logs them but keeps the clock running so a short
 * capture hiccup does not tear down the monitor session.
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <fcntl.h>
#include <unistd.h>
#include <signal.h>
#include <sys/mman.h>
#include <sys/ioctl.h>
#include <sys/file.h>
#include <sys/select.h>
#include <linux/i2c-dev.h>
#include <time.h>
#include <errno.h>

#define FIFO_DEPTH 8192
#define PREFILL 2048
#define BLOCK_SAMPLES 4096
#define STREAM_TOTAL 0xFFFFFFFFu

static volatile sig_atomic_t interrupted;
static void stop(int s){(void)s;interrupted=1;}
static double now(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+t.tv_nsec*1e-9;}
static int wr(int fd,uint8_t reg,uint8_t value){uint8_t b[3]={0x40,reg,value};return write(fd,b,3)==3?0:-1;}
static void nap(void){struct timespec t={0,1000000};nanosleep(&t,NULL);}

static unsigned long dropped;
static volatile uint32_t *regs;

static int push_sample(int16_t sample){
    int tries=0;
    while(regs[2]>=FIFO_DEPTH&&!interrupted&&tries<100){nap();tries++;}
    if(regs[2]>=FIFO_DEPTH){dropped++;return -1;}
    regs[2]=(uint16_t)sample;
    return 0;
}

int main(int argc,char **argv){
    if(argc!=4){fprintf(stderr,"usage: pcm_stream <uio> <i2c> <mmap-size>\n");return 2;}
    size_t size=(size_t)strtoul(argv[3],NULL,10);
    int fd=-1,i2c=-1,owned=0,configured=0,started=0,rc=1;
    volatile uint32_t *r=MAP_FAILED;
    unsigned last_under=0;
    double last_report=0;
    signal(SIGINT,stop);signal(SIGTERM,stop);

    fd=open(argv[1],O_RDWR|O_CLOEXEC);
    if(fd<0||flock(fd,LOCK_EX|LOCK_NB)){perror("UIO lock");goto done;}
    owned=1;
    r=mmap(NULL,size,PROT_READ|PROT_WRITE,MAP_SHARED,fd,0);
    if(r==MAP_FAILED||r[3]!=0x53414631){fprintf(stderr,"FIFO hardware signature mismatch\n");goto done;}
    regs=r;
    i2c=open(argv[2],O_RDWR|O_CLOEXEC);
    if(i2c<0||ioctl(i2c,I2C_SLAVE,0x3b)<0){perror("I2C");goto done;}
    configured=1;

    /* Reset counters, set an effectively unlimited total, configure codec. */
    r[4]=0xA5000001;r[3]=STREAM_TOTAL;
    if(wr(i2c,0x23,(40<<2)|3)||wr(i2c,0x24,(40<<2)|3)||
       wr(i2c,0x1c,0x21)||wr(i2c,0x1e,0x41))goto done;

    int16_t prefill[PREFILL];
    size_t got=0;
    while(got<sizeof(prefill)&&!interrupted){
        ssize_t n=read(0,(char*)prefill+got,sizeof(prefill)-got);
        if(n<0&&errno==EINTR)continue;
        if(n<=0)break;
        got+=(size_t)n;
    }
    if(got<4){fprintf(stderr,"no audio before prefill\n");goto done;}
    for(size_t k=0;k<got/2;k++)if(push_sample(prefill[k]))break;
    r[4]=0xA5000002;started=1;

    int16_t block[BLOCK_SAMPLES];
    for(;;){
        size_t have=0;int eof=0;
        while(have<sizeof(block)){
            if(interrupted){eof=1;break;}
            fd_set fds;FD_ZERO(&fds);FD_SET(0,&fds);
            struct timeval tv={0,200000};
            int ready=select(1,&fds,NULL,NULL,&tv);
            if(ready<0){if(errno==EINTR)continue;perror("select");eof=1;break;}
            if(ready==0)continue;
            ssize_t n=read(0,(char*)block+have,sizeof(block)-have);
            if(n<0&&errno==EINTR)continue;
            if(n<=0){eof=1;break;}
            have+=(size_t)n;
        }
        size_t count=have/2;
        for(size_t k=0;k<count&&!interrupted;k++)push_sample(block[k]);
        if(regs[1]!=last_under&&now()-last_report>1.0){
            fprintf(stderr,"hardware underrun=%u dropped=%lu\n",regs[1],dropped);
            last_under=regs[1];last_report=now();
        }
        if(eof)break;
    }

    /* Let the last queued samples leave the FIFO, but do not wait forever. */
    if(started&&!interrupted){
        double deadline=now()+1.0;
        while(regs[2]>0&&now()<deadline){nap();}
    }
    rc=0;
done:
    if(r!=MAP_FAILED&&owned&&r[3]==0x53414631)r[4]=0xA5000000;
    if(configured){wr(i2c,0x1c,0x01);wr(i2c,0x1e,0x01);}
    if(i2c>=0)close(i2c);
    if(r!=MAP_FAILED){
        printf("stream complete played=%u underruns=%u dropped=%lu\n",
               r[0],r[1],dropped);
        fflush(stdout);
        munmap((void*)r,size);
    }
    if(owned)flock(fd,LOCK_UN);
    if(fd>=0)close(fd);
    return rc;
}
