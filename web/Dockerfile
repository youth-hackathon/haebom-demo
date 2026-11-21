# 시연 페이지와, 기기 화면·시연 API로 가는 프록시. 비밀번호(htpasswd)와 https 인증서(openssl)를 만드는 도구가 들어 있습니다.
FROM nginx:1.27-alpine
RUN apk add --no-cache apache2-utils openssl
COPY 10-auth.sh /docker-entrypoint.d/10-auth.sh
RUN chmod +x /docker-entrypoint.d/10-auth.sh && rm -f /etc/nginx/conf.d/default.conf
COPY default.conf.template /etc/nginx/templates/default.conf.template
COPY www/ /var/www/haebom/
ENV DEVICE_HOST=device API_HOST=api
