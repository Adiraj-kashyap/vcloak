#!/usr/bin/env bash
# M08 S4 - Nsight Compute divergence profile (Linux runner). All the logic is in bench/run_ncu.py.
# Usage: bash bench/run_ncu.sh [--seed 8] [--log2n 16] [--out runs]
set -u
cd "$(dirname "$0")/.."
exec "${PYTHON:-python}" bench/run_ncu.py "$@"
