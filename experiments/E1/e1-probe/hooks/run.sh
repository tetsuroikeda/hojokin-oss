#!/bin/sh
# 実験 E1 の起動用スクリプト
exec python3 "$(dirname "$0")/probe.py" "$1"
