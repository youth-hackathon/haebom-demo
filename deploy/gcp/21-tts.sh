#!/usr/bin/env bash
# haebom-tts를 받아 127.0.0.1:8766에 띄웁니다. 다시 돌리면 최신으로 갱신해 다시 띄웁니다.
set -euo pipefail
SRC="${1:-$HOME/haebom-src/vm}"
DIR="$HOME/haebom-tts"
if [ -d "$DIR/.git" ]; then git -C "$DIR" pull --ff-only; else git clone https://github.com/youth-hackathon/haebom-tts.git "$DIR"; fi
install -m 644 "$SRC/tts/docker-compose.override.yml" "$DIR/docker-compose.override.yml"
# .env가 없으면 키 없이 baseline 엔진으로 시작합니다. Gemini를 쓰려면 .env에 키를 넣고 다시 실행합니다.
if [ ! -f "$DIR/.env" ]; then ( umask 077; printf 'GEMINI_API_KEY=\nTTS_ENGINE=baseline\n' > "$DIR/.env" ); fi
chmod 600 "$DIR/.env"
cd "$DIR" && sudo docker compose up -d --build
for _ in $(seq 30); do curl -fs -m 2 http://127.0.0.1:8766/health && break; sleep 1; done; echo
