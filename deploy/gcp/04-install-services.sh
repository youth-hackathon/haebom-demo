#!/usr/bin/env bash
# VM 안에서 실행. ~/haebom-src 에 올린 vm/ 내용을 설치하고 비밀번호가 없으면 만듭니다.
set -euo pipefail
SRC="${1:-$HOME/haebom-src/vm}"
CONF="$HOME/.config/haebom"
mkdir -p "$HOME/haebom/bin" "$CONF"
install -m 755 "$SRC/bin/haebom-part.sh" "$HOME/haebom/bin/"
install -m 644 "$SRC/openbox-rc.xml" "$CONF/openbox-rc.xml"
if [ ! -f "$CONF/vnc-password.txt" ]; then
  ( umask 077; head -c 256 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | cut -c1-8 | tr -d '\n' > "$CONF/vnc-password.txt" )
fi
( umask 077; x11vnc -storepasswd "$(cat "$CONF/vnc-password.txt")" "$CONF/vnc.pass" >/dev/null 2>&1 )
chmod 600 "$CONF/vnc-password.txt" "$CONF/vnc.pass"
sudo install -m 644 "$SRC"/systemd/haebom-*.service "$SRC"/systemd/haebom-emu@.target /etc/systemd/system/
sudo systemctl daemon-reload
echo "installed. password file: $CONF/vnc-password.txt"
