#!/bin/bash
# VocaAudio 실행 스크립트
# 더블클릭으로 실행 가능

cd "$(dirname "$0")"
./venv/bin/python vocaaudio_gui.py
