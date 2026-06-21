#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""包装脚本，确保测试输出UTF-8编码"""
import sys
import io
import subprocess

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

result = subprocess.run(
    [sys.executable, 'batch_takeover_test.py', '--mode', 'regression'],
    capture_output=True,
    text=True,
    encoding='utf-8',
    errors='replace'
)

print(result.stdout)
if result.stderr:
    print(result.stderr, file=sys.stderr)

sys.exit(result.returncode)
