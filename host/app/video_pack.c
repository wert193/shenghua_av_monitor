#include <stdint.h>
// Boundary padding/format conversion only; convolution runs in FPGA.
void video_pack(const uint8_t *src,uint32_t *dst,unsigned w,unsigned h){
 for(unsigned y=0;y<h+2;y++){
  unsigned sy=y==0?0:(y>h?h-1:y-1);
  const uint8_t *row=src+sy*w*3;
  for(unsigned x=0;x<w+2;x++){
   unsigned sx=x==0?0:(x>w?w-1:x-1);
   const uint8_t *p=row+sx*3;
   *dst++=(uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16);
  }
 }
}
void video_unpack(const uint32_t *src,uint8_t *dst,unsigned n){
 for(unsigned i=0;i<n;i++){
  uint32_t p=*src++;*dst++=p;*dst++=p>>8;*dst++=p>>16;
 }
}
