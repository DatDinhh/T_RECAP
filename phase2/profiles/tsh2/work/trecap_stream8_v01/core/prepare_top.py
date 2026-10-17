"""Derive stream wrapper while preserving frozen numerical core/completion logic."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
out=Path(__file__).resolve().parent
s=(ROOT/'outputs/trecap_hps_transport_v01/core_overlay02/trecap_pcm_replay_top.sv').read_text()
def replace(old,new):
    global s
    assert old in s,old
    s=s.replace(old,new)
replace('trecap_pcm_replay_top','trecap_pcm_stream_top')
replace('REPLAY_MEM_DEPTH','INPUT_FIFO_DEPTH')
replace('INPUT_FIFO_DEPTH      = 1024','INPUT_FIFO_DEPTH      = 256')
replace('INPUT_SAMPLES         = 1024','INPUT_SAMPLES         = 384000')
replace('    // Upload is synchronous and allowed only while the finite source is idle.\n    // The enclosing host adapter owns sequential completeness and epoch locking.\n    input  logic                         load_we_i,\n    input  logic [9:0]                   load_addr_i,\n    input  logic signed [11:0]           load_data_i,',
'''    // Input remains a single epoch across arbitrary host pauses/chunk boundaries.
    input  logic                         pcm_valid_i,
    output logic                         pcm_ready_o,
    input  logic signed [11:0]           pcm_data_i,
    output logic [63:0]                  pcm_accepted_count_o,
    output logic [31:0]                  pcm_fifo_level_o,
    // Counter increments only on the exporter's final accepted byte of each record.
    input  logic [63:0]                  export_emitted_frames_i,''')
replace('        (INPUT_FIFO_DEPTH == 1024) &&\n        (INPUT_SAMPLES == 1024) &&\n        (INPUT_SAMPLES <= INPUT_FIFO_DEPTH) &&',
'''        (INPUT_FIFO_DEPTH >= 2) &&
        ((INPUT_FIFO_DEPTH & (INPUT_FIFO_DEPTH-1)) == 0) &&
        (INPUT_SAMPLES > 0) &&''')
replace('    assign analysis_tick_valid_w = bram_sample_valid_w &&',
'''    // Reserve one exporter slot before each new hop. The existing tap is
    // observation-only; source admission is the sole throttle and enable stays high.
    // Once a hop is admitted, all128 samples may proceed. The next hop waits
    // for its predecessor's final export-byte handshake, bounding outstanding
    // frames by one even under unlimited downstream backpressure.
    wire analysis_credit_w = bram_sample_idx_w <
        ((export_emitted_frames_i + 64'd1) * 64'(T_HOP_H));
    assign analysis_tick_valid_w = bram_sample_valid_w && analysis_credit_w &&''')
replace('        core_sample_ready_w : tail_tick_ready_w;',
'        (core_sample_ready_w && analysis_credit_w) : tail_tick_ready_w;')
replace('trecap_pcm_replay_source #(','trecap_pcm_stream_source #(')
replace('.MEM_DEPTH( INPUT_FIFO_DEPTH )','.FIFO_DEPTH( INPUT_FIFO_DEPTH )')
replace('        .load_we_i( load_we_i ), .load_addr_i( load_addr_i ), .load_data_i( load_data_i ),',
'''        .pcm_valid_i( pcm_valid_i ), .pcm_ready_o( pcm_ready_o ), .pcm_data_i( pcm_data_i ),
        .pcm_accepted_count_o( pcm_accepted_count_o ), .pcm_fifo_level_o( pcm_fifo_level_o ),''')
replace('        if (INPUT_SAMPLES > INPUT_FIFO_DEPTH) begin\n            $fatal(1, "trecap_pcm_stream_top: INPUT_SAMPLES exceeds INPUT_FIFO_DEPTH");\n        end\n','')
s='// Streaming overlay: numerical datapath unchanged; see README.md.\n'+s
(out/'trecap_pcm_stream_top.sv').write_text(s)
print(out/'trecap_pcm_stream_top.sv')
