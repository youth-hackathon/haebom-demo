#!/bin/sh
# nginx가 뜨기 전에 한 번 돕니다: 비밀번호 설정과 https 인증서.
set -eu

# DEMO_PASSWORD가 있으면 모든 경로에 비밀번호를 겁니다. 없으면 걸지 않습니다(이 컴퓨터에서만 볼 때).
if [ -n "${DEMO_PASSWORD:-}" ]; then
  htpasswd -bc /etc/nginx/haebom.htpasswd "${DEMO_USER:-haebom}" "$DEMO_PASSWORD" 2>/dev/null
  printf 'auth_basic "haebom";\nauth_basic_user_file /etc/nginx/haebom.htpasswd;\n' > /etc/nginx/haebom-auth.conf
  echo "haebom web: 비밀번호를 겁니다 (아이디 ${DEMO_USER:-haebom})"
else
  printf 'auth_basic off;\n' > /etc/nginx/haebom-auth.conf
  echo "haebom web: 비밀번호 없이 엽니다 (DEMO_PASSWORD가 비어 있음)"
fi

# https 인증서: /etc/nginx/tls 에 cert.pem, key.pem 을 넣어 두면 그것을 쓰고, 없으면 자체 서명한 것을 만듭니다.
mkdir -p /etc/nginx/tls
if [ ! -s /etc/nginx/tls/cert.pem ] || [ ! -s /etc/nginx/tls/key.pem ]; then
  openssl req -x509 -newkey rsa:2048 -nodes -days 30 -subj "/CN=haebom-demo" \
    -keyout /etc/nginx/tls/key.pem -out /etc/nginx/tls/cert.pem >/dev/null 2>&1
  echo "haebom web: 자체 서명 인증서를 만들었습니다 (브라우저가 경고를 한 번 보여 줍니다)"
fi
