# GCP VM에 Docker로 올리기 (작업 지시문)

이 문서는 GCP에 접속할 수 있는 작업자(사람이나 에이전트)에게 그대로 넘기는 지시문입니다. 키와 비밀번호는 여기에 적지 않고, 작업을 시킨 사람에게서 따로 받습니다.

## 할 일

GCP VM `haebom-emu`에 이 저장소(`youth-hackathon/haebom-demo`)의 `docker compose`를 띄워, 밖에서 `https://<이름>/haebom/`으로 해봄 체험 페이지가 열리게 합니다. 페이지에서 Android 폰 4대 가운데 하나를 골라 직접 쓰고, 폰의 소리가 브라우저로 나오고, 브라우저의 마이크가 폰으로 들어가야 합니다.

끝났다고 말할 수 있는 때는 **VM 밖의 컴퓨터에서** `checks/check_remote.py`가 `"problems": []`로 끝났을 때입니다.

## 지금 있는 것

- VM: `haebom-emu`, `asia-northeast3-a`, `n2-standard-16`(CPU 16개, 메모리 64GB), Ubuntu 24.04, 디스크 100GB, 중첩 가상화 켜짐, 태그 `haebom-emu`, 사용자 `haebom`. 공인 IP는 임시 주소라 VM을 껐다 켜면 바뀝니다.
- 방화벽 규칙: `haebom-emu-web`(tcp:6080-6089), `haebom-emu-webrtc`(udp:15550-15599).
- VM에는 예전 방식이 떠 있습니다(`deploy/gcp/README.md`): Cuttlefish를 직접 설치해 기기 4대를 띄우는 systemd 서비스 `haebom-orchestrator`, `haebom-cuttlefish`, `haebom-watch`, 6080의 nginx, 그리고 6081의 TTS 서버(Docker). 새 방식과 포트(15550-15599, 1443, 6520~)와 CPU가 겹칩니다.
- 새 방식은 저장소 맨 위의 `docker-compose.yml` 하나입니다. 구성과 설정은 `README.md`에 있습니다. `artemis`, `tts`, `front` 이미지는 공개 저장소의 main에서 빌드되고, 폰에 깔 앱은 `app/haebom-debug.apk`로 들어 있습니다. 저장소에 없는 것은 `.env`와 `secrets/`뿐입니다.
- 새 방식은 Windows의 Docker Desktop(CPU 16개)에서 확인했습니다(`README.md`의 "확인한 것"). **클라우드 VM에서는 한 번도 띄워 보지 않았습니다.** 특히 다른 컴퓨터의 브라우저에서 WebRTC(폰 화면, 소리, 마이크)가 붙는지는 이 작업에서 처음 확인하는 것입니다.

## 받아야 하는 것

작업을 시킨 사람에게 아래 네 가지를 받습니다. 받은 값은 VM의 파일에만 넣고, 저장소·커밋·로그·보고에 적지 않습니다.

| 무엇 | 어디에 넣는가 |
|---|---|
| 비공개 저장소 `youth-hackathon/haebom-demo`를 받을 권한(GitHub 토큰이나 배포 키). 없으면 받은 저장소 폴더를 VM으로 복사해도 됩니다 | VM의 git 설정 |
| artemis의 키 파일. `haebom-artemis`의 `relay/.env`와 같은 내용(`LETSUR_API_KEY`, `OPENROUTER_API_KEY`와 그 파일에 있는 나머지 값) | `secrets/artemis.env` |
| 음성 키. `TTS_ENGINE=gemini`와 `GEMINI_API_KEY=...` 두 줄 | `secrets/tts.env` |
| 체험 페이지의 비밀번호 | `.env`의 `DEMO_PASSWORD` |

## 순서

1. **VM을 봅니다.** 머신 타입, CPU 수(`nproc`), 메모리(`free -g`), 디스크 여유(`df -h /`), 공인 IP, `/dev/kvm`이 있는지. 공인 IP가 임시 주소면 지금 주소를 고정 주소로 바꿉니다(`gcloud compute addresses create ... --addresses=<지금 IP>`). 인증서의 이름이 IP에서 나오므로, 주소가 바뀌면 인증서를 다시 받아야 합니다.

2. **예전 방식을 내립니다.** `haebom-watch`, `haebom-cuttlefish`, `haebom-orchestrator`를 멈추고 끕니다(`systemctl disable --now`). 남은 기기를 지우고(`cvd reset -y`), 호스트의 `cuttlefish-operator`와 `cuttlefish-host_orchestrator`도 멈추고 끕니다(1443, 2080 포트를 씁니다). nginx에서는 6080의 기기 화면 사이트만 끕니다.
   **6081의 TTS 서버는 그대로 둡니다.** 팀원이 쓰는 앱 빌드가 그 주소를 보고 있을 수 있습니다. 내려야 할 이유가 생기면 먼저 묻습니다.

3. **Docker를 확인합니다.** `docker compose version`이 2.24 이상이어야 합니다(`env_file`의 `required: false`, `dockerfile_inline`을 씁니다). 없거나 낮으면 Docker의 공식 apt 저장소에서 `docker-ce`와 `docker-compose-plugin`을 설치합니다.

4. **저장소를 받고 설정을 씁니다.** `~/haebom-demo`에 받고 `cp .env.example .env`, `mkdir -p secrets`. 받은 키 파일 두 개를 `secrets/`에 넣습니다. `.env`는 이렇게 채웁니다.

   ```
   DEMO_PASSWORD=<받은 값>
   WEB_BIND=0.0.0.0
   WEBRTC_BIND=0.0.0.0
   WEB_PORT=80
   WEB_TLS_PORT=443
   CF_DEVICES=4
   CF_CPUS=<아래 규칙>
   CF_MEMORY_MB=<아래 규칙>
   ```

   **폰의 자원은 이 VM이 가진 것을 다 씁니다.** 이 VM은 이 일만 합니다. 폰은 화면을 GPU 없이 CPU로 그리므로 폰의 속도는 CPU 수가 정합니다.
   - `CF_CPUS` = VM의 CPU 수 ÷ 2. CPU 16개면 8입니다. 4대의 합이 VM의 CPU 수의 두 배가 되는데, 쉬는 폰은 CPU를 거의 쓰지 않아서 이렇게 줍니다. 확인한 컴퓨터가 바로 이 비율이었습니다(CPU 16개에 폰마다 8개, 안내 한 번이 41~44초. 폰마다 4개일 때는 135초).
   - `CF_MEMORY_MB` = 8192. 메모리가 48GB보다 적으면 (메모리 − 8GB) ÷ 4.
   - 해상도(540×1200)와 주사율(30Hz)은 기본값을 둡니다. 그릴 양을 줄여 놓은 값입니다.
   - 머신을 더 큰 것(예: `n2-standard-32`)으로 바꾸면 폰마다 CPU 8개가 온전히 돌아갑니다. 비용과 쿼터가 걸린 일이니 **바꾸기 전에 묻습니다.** AMD 머신(N2D 등)은 중첩 가상화가 안 되므로 고르지 않습니다.

5. **방화벽을 엽니다.** tcp 80과 443, 그리고 15550-15599를 tcp와 udp 둘 다(지금 규칙은 udp만 있습니다). 대상은 태그 `haebom-emu`입니다. 6520~(adb)과 1443은 열지 않습니다. compose가 127.0.0.1에만 엽니다.

6. **https 인증서를 받습니다.** 마이크는 https에서만 켜집니다(브라우저의 제한). 도메인 없이 받는 방법입니다.
   - 이름: 공인 IP의 점을 줄표로 바꾸고 `.sslip.io`를 붙입니다. `34.64.0.1`이면 `34-64-0-1.sslip.io`. 이 이름은 그 IP로 풀립니다.
   - `certbot certonly --standalone -d <이름>`으로 Let's Encrypt 인증서를 받습니다. 80 포트가 비어 있어야 하므로 compose를 띄우기 전에 합니다. 계정 이메일이 필요하면 묻거나 `--register-unsafely-without-email`을 씁니다.
   - 받은 `fullchain.pem`을 `secrets/tls/cert.pem`으로, `privkey.pem`을 `secrets/tls/key.pem`으로 복사합니다(심볼릭 링크가 아니라 파일로).
   - 받지 못하면(sslip.io 이름은 발급 한도에 걸릴 수 있습니다) `.nip.io`로 한 번 더 해 보고, 그래도 안 되면 `secrets/tls/`를 비워 둡니다. 그러면 자체 서명 인증서가 만들어지고 브라우저가 경고를 한 번 보여 줍니다. 이 경우를 보고에 적습니다.

7. **띄웁니다.** `docker compose up -d --build`. 처음에는 이미지 세 개를 빌드하고 Android 이미지(약 2GB)를 받아 폰 4대를 만들어서 15~25분 걸립니다. `docker compose logs -f device`에 "기기 4대가 준비되었습니다"가 나오고 `docker compose ps`에서 `device`가 `healthy`가 될 때까지 기다립니다. 그 뒤 15초쯤 지나 `curl -u haebom:<비밀번호> https://<이름>/haebom/api/devices`가 폰 4대를 `idle`로 답해야 합니다.

8. **VM 밖에서 확인합니다.** 자기 컴퓨터에서(VM 안에서 하면 뜻이 없습니다):

   ```
   pip install playwright && playwright install chromium
   DEMO_AUTH=haebom:<비밀번호> python checks/check_remote.py https://<이름>
   ```

   - `"problems": []`이어야 합니다.
   - `"2 video"`에 영상의 크기(540×1200)와 받은 장 수가 있으면 폰 화면이 다른 컴퓨터에서 붙은 것입니다. `"3 connected to"`는 어느 주소로 붙었는지의 참고값입니다(브라우저가 주소를 비워서 줄 때가 있습니다).
   - 영상이 안 오면 방화벽(15550-15599 tcp/udp), `.env`의 `WEBRTC_BIND`, `docker compose port device 15550`을 차례로 봅니다. 폰이 알려 주는 주소는 컨테이너 안의 주소라서 페이지가 "이 페이지를 연 주소의 같은 포트"를 후보로 더합니다(`web/www/tune.js`). 이 부분은 다른 컴퓨터에서 확인된 적이 없으니, 안 되면 브라우저의 `chrome://webrtc-internals`에서 후보 목록을 보고 무엇이 빠졌는지 찾습니다.
   - 사람 귀와 입으로 하는 확인도 한 번 합니다: Chrome으로 열어 폰을 고르고, **소리 켜기**를 누른 뒤 "글자 크기 키우기"를 눌러 안내 음성이 들리는지, **마이크 켜기**를 눌렀을 때 권한을 묻는지.

## 하지 않는 것

- 키, 토큰, 비밀번호, 음성 서버의 주소를 저장소·커밋·로그·보고에 적지 않습니다.
- `device/entrypoint.sh`를 컨테이너가 도는 동안 고치지 않습니다. 실행 중인 파일이라 고치면 컨테이너가 다시 켜집니다. 고쳐야 하면 `docker compose stop device` 뒤에 고칩니다.
- 누가 폰을 쓰는 중일 때 `device`나 `web`을 다시 띄우지 않습니다. 먼저 `/haebom/api/devices`로 `busy`인 폰이 없는지 봅니다. `api`는 다시 띄워도 잠금이 남습니다.
- adb로 폰에 입력을 보내야 하면 먼저 그 폰을 `POST /haebom/api/claim`으로 잡습니다. 잡지 않은 폰은 읽기만 합니다.
- 저장소를 고쳤으면 강제로 덮어쓰지 않고(`--force` 금지) 커밋을 쌓아 올립니다.
- `deploy/gcp/`의 예전 스크립트와 VM의 `~/cf`, `~/.config/haebom/`은 지우지 않습니다.

## 보고할 것

- 체험 페이지의 주소와 아이디. 비밀번호는 값이 아니라 어디에 적어 두었는지.
- VM의 머신 타입, 폰마다 준 CPU와 메모리.
- 인증서를 어떻게 받았는지(Let's Encrypt인지 자체 서명인지).
- `check_remote.py`가 찍은 JSON 전체, 그리고 귀와 입으로 확인한 결과.
- 하지 못한 것과 그 까닭.
