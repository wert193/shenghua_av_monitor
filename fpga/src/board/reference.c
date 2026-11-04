#include <stdint.h>
#include <string.h>
#ifdef _WIN32
#define EXPORT __declspec(dllexport)
#else
#define EXPORT
#endif
EXPORT void fir_reference(const int32_t *input, int32_t *output, unsigned n,
                          const int32_t *coeff, int16_t *history, unsigned *head, int reset) {
    if(reset) { memset(history,0,256*sizeof(*history)); *head=0; }
    for(unsigned i=0;i<n;i++) {
        *head=(*head-1)&255;
        history[*head]=(int16_t)input[i];
        int64_t sum=0;
        for(unsigned k=0;k<255;k++) sum+=(int64_t)history[(*head+k)&255]*coeff[k];
        int64_t a=sum+16384;
        int64_t result=a>=0 ? a/32768 : -((-a+32767)/32768);
        output[i]=result>32767 ? 32767 : result< -32768 ? -32768 : (int32_t)result;
    }
}
