#include "audio_fir.h"
#include "coefficients.h"

void audio_fir(hls::stream<AudioWord>& input, hls::stream<AudioWord>& output,
               unsigned count, unsigned mode, unsigned clear_history) {
#pragma HLS INTERFACE axis port=input
#pragma HLS INTERFACE axis port=output
#pragma HLS INTERFACE s_axilite port=count bundle=control
#pragma HLS INTERFACE s_axilite port=mode bundle=control
#pragma HLS INTERFACE s_axilite port=clear_history bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
    static ap_int<16> history[256] = {};
    static ap_uint<8> head = 0;
#pragma HLS ARRAY_PARTITION variable=history cyclic factor=4 dim=1
#pragma HLS ARRAY_PARTITION variable=COEFFICIENTS cyclic factor=4 dim=2
    if (clear_history) {
        reset_loop: for (int k=0;k<256;k++) {
#pragma HLS PIPELINE II=1
            history[k]=0;
        }
        head=0;
    }
    const unsigned selected = mode & 3;
    sample_loop: for (unsigned n=0;n<count;n++) {
#pragma HLS LOOP_TRIPCOUNT min=1 max=4096 avg=1024
        AudioWord word=input.read();
        head=head-1;
        history[head]=ap_int<16>(word.data.range(15,0));
        ap_int<40> partial[4]={0,0,0,0};
#pragma HLS ARRAY_PARTITION variable=partial complete
        tap_loop: for (int t=0;t<64;t++) {
#pragma HLS PIPELINE II=1
            lane_loop: for (int j=0;j<4;j++) {
#pragma HLS UNROLL
                ap_uint<8> position=head+t*4+j;
                ap_int<18> coefficient=COEFFICIENTS[selected][t*4+j];
                partial[j] += history[position]*coefficient;
            }
        }
        ap_int<42> sum=ap_int<42>(partial[0])+partial[1]+partial[2]+partial[3];
        // Round half toward +infinity, then saturate signed PCM16.
        ap_int<42> rounded=(sum+16384)>>15;
        ap_int<32> result=rounded>32767 ? 32767 : rounded< -32768 ? -32768 : (int)rounded;
        AudioWord out;
        out.data=result;
        out.keep=15; out.strb=15; out.last=(n==count-1);
        output.write(out);
    }
}
