from vcloak import config


def test_brief_parameters():
    # ai/PROJECT_BRIEF.md §7 defaults
    assert config.EPOCH_MS == 200
    assert (config.SLOTS_DEV, config.SLOTS_BENCH) == (64, 65536)
    assert config.SLOTS == config.SLOTS_DEV
    assert config.WINDOW_S == 60 and config.WINDOW_S in config.WINDOW_S_ABLATION
    assert config.BUCKETS == 64
    assert config.CAND_K == 128
    assert config.BLOCK == 4096
    assert config.TAG_BITS == 128


def test_slots_are_powers_of_two():
    for s in (config.SLOTS_DEV, config.SLOTS_BENCH):
        assert s & (s - 1) == 0


def test_timing_rules():
    assert config.TIMING_WARMUP >= 10
    assert config.TIMING_RUNS >= config.TIMING_RUNS_MIN >= 30


def test_max_log2n():
    # floor(log2(0.5 * free / 48)), capped at 24
    assert config.max_log2n(2 * 48 * 1024) == 10
    assert config.max_log2n(2 * 48 * 1024 - 1) == 9
    assert config.max_log2n(2 * 48 * 2**24) == 24
    assert config.max_log2n(2 * 48 * 2**24 - 1) == 23
    assert config.max_log2n(2**40) == config.MAX_LOG2N_CAP
    assert config.max_log2n(0) == 0
