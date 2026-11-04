#pragma once
#include <ap_int.h>
#include <ap_axi_sdata.h>
#include <hls_stream.h>
typedef ap_axiu<32,0,0,0> AudioWord;
void audio_fir(hls::stream<AudioWord>& input, hls::stream<AudioWord>& output,
               unsigned count, unsigned mode, unsigned clear_history);
