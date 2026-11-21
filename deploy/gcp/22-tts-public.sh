#!/usr/bin/env bash
# TTS 서버를 밖에서 http로 닿게 합니다(6081 포트, 비밀 경로). 다시 돌려도 됩니다.
# 비밀 경로를 바꾸려면 ~/.config/haebom/tts-token.txt 를 지우고 다시 실행합니다.
set -euo pipefail
SRC="${1:-$HOME/haebom-src/vm}"
CONF="$HOME/.config/haebom"; mkdir -p "$CONF"
if [ ! -f "$CONF/tts-token.txt" ]; then
  ( umask 077; head -c 256 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | cut -c1-24 | tr -d '\n' > "$CONF/tts-token.txt" )
fi
chmod 600 "$CONF/tts-token.txt"
T=$(cat "$CONF/tts-token.txt")
# 접근 기록에 비밀 경로가 남지 않게 경로를 뺀 기록 형식을 씁니다.
echo 'log_format haebom_notoken '"'"'$remote_addr [$time_local] $request_method $status $body_bytes_sent $request_time'"'"';' \
  | sudo tee /etc/nginx/conf.d/00-haebom-log.conf >/dev/null
sed "s/__TTS_TOKEN__/$T/g" "$SRC/nginx/haebom-tts.conf" | sudo tee /etc/nginx/conf.d/haebom-tts.conf >/dev/null
sudo chmod 640 /etc/nginx/conf.d/haebom-tts.conf
sudo nginx -t && sudo systemctl reload nginx
echo "tts public ok. token file: $CONF/tts-token.txt"
