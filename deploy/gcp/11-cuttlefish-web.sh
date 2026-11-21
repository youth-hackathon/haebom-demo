#!/usr/bin/env bash
# 비밀번호를 건 nginx를 6080에 둡니다. 비밀번호가 없으면 만듭니다. 다시 돌려도 됩니다.
set -euo pipefail
SRC="${1:-$HOME/haebom-src/vm}"
CONF="$HOME/.config/haebom"; mkdir -p "$CONF"
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y nginx-light apache2-utils >/dev/null
if [ ! -f "$CONF/web-password.txt" ]; then
  ( umask 077; head -c 256 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | cut -c1-16 | tr -d '\n' > "$CONF/web-password.txt" )
fi
chmod 600 "$CONF/web-password.txt"
sudo htpasswd -b -c /etc/nginx/haebom.htpasswd haebom "$(cat "$CONF/web-password.txt")" 2>/dev/null
sudo chown root:www-data /etc/nginx/haebom.htpasswd && sudo chmod 640 /etc/nginx/haebom.htpasswd
sudo mkdir -p /var/www/haebom && sudo install -m 644 "$SRC/www/tune.js" "$SRC/www/index.html" /var/www/haebom/
# "만들기"가 보낼 고정된 사양(vm/create.json)을 nginx 설정에 넣습니다.
install -m 644 "$SRC/create.json" "$CONF/create.json"
python3 - "$SRC/nginx/haebom-cuttlefish.conf" "$CONF/create.json" <<'PY' | sudo tee /etc/nginx/conf.d/haebom-cuttlefish.conf >/dev/null
import sys, json
conf = open(sys.argv[1]).read()
body = json.dumps(json.load(open(sys.argv[2])), separators=(",", ":"))
assert "'" not in body
print(conf.replace("__CREATE_JSON__", body), end="")
PY
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl enable --now nginx && sudo systemctl reload nginx
echo "web ok. user: haebom, password file: $CONF/web-password.txt"
