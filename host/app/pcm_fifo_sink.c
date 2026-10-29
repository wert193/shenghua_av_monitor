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
static volatile sig_atomic_t interrupted;
static void stop(int s){(void)s;interrupted=1;}
static double now(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+t.tv_nsec*1e-9;}
static int wr(int fd,uint8_t reg,uint8_t value){uint8_t b[3]={0x40,reg,value};return write(fd,b,3)==3?0:-1;}
static void nap(void){struct timespec t={0,1000000};nanosleep(&t,NULL);}
int main(int argc,char **argv){
 if(argc!=5)return 2;
 unsigned total=(unsigned)strtoul(argv[4],NULL,10),sent=0;
 size_t size=strtoul(argv[3],NULL,10);
 if(!total||size<20||size>1048576)return 2;
 int fd=-1,i2c=-1,owned=0,configured=0,rc=1,started=0;
 volatile uint32_t *r=MAP_FAILED;
 double start=0;
 signal(SIGINT,stop);signal(SIGTERM,stop);
 fd=open(argv[1],O_RDWR|O_CLOEXEC);
 if(fd<0||flock(fd,LOCK_EX|LOCK_NB)){perror("UIO lock");goto done;}
 owned=1;r=mmap(NULL,size,PROT_READ|PROT_WRITE,MAP_SHARED,fd,0);
 if(r==MAP_FAILED||r[3]!=0x53414631){fprintf(stderr,"FIFO hardware signature mismatch\n");goto done;}
 i2c=open(argv[2],O_RDWR|O_CLOEXEC);
 if(i2c<0||ioctl(i2c,I2C_SLAVE,0x3b)<0){perror("I2C");goto done;}
 configured=1;
 r[4]=0xA5000001;r[3]=total;
 if(wr(i2c,0x23,(40<<2)|3)||wr(i2c,0x24,(40<<2)|3)||wr(i2c,0x1c,0x21)||wr(i2c,0x1e,0x41))goto done;
 while(sent<total&&!interrupted){
  int32_t block[4096];size_t count=0;
  unsigned n=total-sent;if(n>4096)n=4096;
  double deadline=now()+3;
  while(count<n*4&&!interrupted){
   fd_set fds;FD_ZERO(&fds);FD_SET(0,&fds);struct timeval tv={0,10000};
   int ready=select(1,&fds,NULL,NULL,&tv);
   if(ready<0&&errno!=EINTR)goto done;
   if(now()>deadline){fprintf(stderr,"Producer timeout\n");goto done;}
   if(ready<=0)continue;
   ssize_t got=read(0,(char*)block+count,n*4-count);
   if(got<=0){if(got<0&&errno==EINTR)continue;fprintf(stderr,"Incomplete audio\n");goto done;}
   count+=(size_t)got;
  }
  for(unsigned k=0;k<n&&!interrupted;k++){
   if(block[k]<-32768||block[k]>32767)goto done;
   deadline=now()+1;
   while(r[2]>=8192&&!interrupted){if(now()>deadline){fprintf(stderr,"FIFO stalled\n");goto done;}nap();}
   r[2]=(uint16_t)block[k];sent++;
   if(!started&&(sent>=4096||sent==total)){
    start=now();r[4]=0xA5000002;started=1;
   }
  }
  if(r[1]){fprintf(stderr,"Hardware underrun=%u; stopping rather than stretching music\n",r[1]);goto done;}
 }
 while(started&&r[0]<total&&!interrupted){
  if(now()-start>total/48000.0+2){fprintf(stderr,"Playback clock timeout\n");goto done;}
  if(r[1]){fprintf(stderr,"Hardware underrun=%u\n",r[1]);goto done;}
  nap();
 }
 // Allow the last latched sample to complete on the serial interface.
 nap();
 printf("FIFO complete submitted=%u played=%u seconds=%.6f expected=%.6f underruns=%u stopped=%d\n",sent,r[0],started?now()-start:0,total/48000.0,r[1],interrupted!=0);
 fflush(stdout);rc=0;
done:
 if(r!=MAP_FAILED&&owned&&r[3]==0x53414631)r[4]=0xA5000000;
 if(configured){wr(i2c,0x1c,0x01);wr(i2c,0x1e,0x01);}
 if(i2c>=0)close(i2c);
 if(r!=MAP_FAILED)munmap((void*)r,size);
 if(owned)flock(fd,LOCK_UN);
 if(fd>=0)close(fd);
 return rc;
}
