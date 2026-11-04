#include "audio_fir.h"
#include "coefficients.h"
#include <vector>
#include <cstdint>
#include <cstdio>
#include <cstdlib>

static std::vector<int> history;
static int failures=0;
static int reference(int x,unsigned mode,bool reset) {
    if (reset) history.clear();
    history.insert(history.begin(),x);
    if(history.size()>255) history.pop_back();
    int64_t sum=0;
    for(unsigned k=0;k<history.size();k++) sum+=int64_t(history[k])*COEFFICIENTS[mode][k];
    // Explicit floor division, independent of signed right-shift behavior.
    int64_t a=sum+16384;
    int64_t y=a>=0 ? a/32768 : -((-a+32767)/32768);
    return y>32767?32767:y< -32768?-32768:int(y);
}
static void check(const std::vector<int>& x,unsigned mode,bool reset) {
    hls::stream<AudioWord> input,output;
    for(unsigned n=0;n<x.size();n++) {
        AudioWord w; w.data=ap_int<32>(x[n]); w.keep=15; w.strb=15; w.last=(n==x.size()-1);
        input.write(w);
    }
    audio_fir(input,output,x.size(),mode,reset);
    for(unsigned n=0;n<x.size();n++) {
        if(output.empty()) { puts("FAIL missing output"); std::exit(1); }
        AudioWord w=output.read();
        int actual=ap_int<32>(w.data).to_int();
        int expect=reference(x[n],mode,reset&&n==0);
        if(actual!=expect || w.keep!=15 || w.strb!=15 || bool(w.last)!=(n==x.size()-1)) {
            if(failures++<8) printf("FAIL mode=%u n=%u actual=%d expected=%d\n",mode,n,actual,expect);
        }
    }
    if(!input.empty()||!output.empty()) { puts("FAIL extra tokens"); failures++; }
}
int main() {
    uint32_t seed=0x12345678;
    for(unsigned mode=0;mode<4;mode++) {
        std::vector<int> impulse(260,0); impulse[0]=32767; impulse[1]=-32768;
        check(impulse,mode,true);
        std::vector<int> random(273);
        for(unsigned n=0;n<random.size();n++) { seed=1664525u*seed+1013904223u; random[n]=int(seed>>16)-32768; }
        check(std::vector<int>(random.begin(),random.begin()+17),mode,true);
        check(std::vector<int>(random.begin()+17,random.end()),mode,false);
    }
    // Mode changes preserve sample history across DMA transactions.
    check(std::vector<int>(270,32767),0,true);
    check(std::vector<int>(19,-32768),1,false);
    check(std::vector<int>(31,32767),2,false);
    check(std::vector<int>(263,-12345),3,false);
    check(std::vector<int>(1,0),3,true);
    if(failures) return 1;
    puts("PASS: all four modes, signed extremes, ring wraps, history continuity, reset, saturation and TLAST.");
    return 0;
}
