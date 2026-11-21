# haebom-demo

해봄 시연 환경. GCP VM에서 Cuttlefish(Android 가상 기기) 4대를 띄우고 웹 링크로 보고 조작합니다.

- [`deploy/gcp/`](deploy/gcp/README.md): VM 설정 스크립트, systemd와 nginx 설정, TTS 서버 배포, 측정 도구

비밀번호와 키는 저장소에 없습니다. VM 안의 파일(`~/.config/haebom/`, `~/haebom-tts/.env`)에서 읽습니다.
