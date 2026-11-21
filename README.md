# haebom-demo

해봄 시연 환경입니다. 브라우저 한 화면에 Android 가상 기기와 안내 진행 상황이 같이 나옵니다. 보는 사람이 기기 화면을 직접 누르고, 해봄은 다음에 누를 곳만 짚습니다.

전체가 Docker 안에서 돕니다. 내 컴퓨터에서나 서버(VM)에서나 같은 명령으로 띄우고 같은 주소 모양으로 엽니다.

```bash
cp .env.example .env            # 비밀번호와 여는 범위를 적습니다
mkdir -p secrets                # 모델 키, TTS 키를 넣습니다 (아래 "키" 참고)
docker compose up -d --build
```

- 시연 페이지: <http://127.0.0.1:6080/haebom/> (https는 `https://127.0.0.1:6443/haebom/`)
- 처음 켤 때는 Android 이미지(약 2GB)를 받고 기기를 만들어서 15~20분 걸립니다. 그동안 페이지에는 "기기를 준비하고 있어요"가 나옵니다. 두 번째부터는 1~2분입니다.

## 화면

| 자리 | 내용 |
|---|---|
| 왼쪽 | 실제 Android 기기 화면. 마우스로 누르고 끌 수 있고, 키보드 입력도 들어갑니다. 아래에 소리 켜기, 마이크 켜기, 처음 상태로 버튼이 있습니다 |
| 오른쪽 위 | 할 일 고르기. 검증된 매뉴얼이 있는 일은 카드로 나오고, 그 밖의 일은 직접 적습니다 |
| 오른쪽 가운데 | 안내 진행. 단계마다 무엇을 안내했는지, 누가 답했는지(매뉴얼 / 폰 설정값 / AI / 기다림), 답하는 데 걸린 시간 |
| 오른쪽 아래 | 지금 폰의 실제 값(글자 크기, 켜진 알람). 안내가 "다 했어요"라고 말하는 근거입니다 |

기기 화면, 터치, 키보드, 소리, 마이크는 모두 WebRTC로 오갑니다. 소리와 마이크는 브라우저 정책 때문에 버튼을 한 번 눌러야 켜집니다. 마이크는 https 주소나 `localhost`·`127.0.0.1`로 열었을 때만 켤 수 있습니다(브라우저의 제한).

## 구성

```
브라우저 ──http(s)──▶ web ──▶ device   기기 화면(Cuttlefish 웹 클라이언트), WebRTC 신호
   │                   └────▶ api      안내 시작·멈춤·처음 상태로, 진행 기록
   └──WebRTC(15550-15599)──▶ device    영상, 소리, 마이크, 터치

api ──adb──▶ device                    앱 설치, 접근성 서비스 켜기, 요청 보내기, 로그 읽기
device 안의 해봄 앱 ──▶ api ──▶ front ──▶ artemis ──▶ 모델
                          └──▶ tts
```

| 서비스 | 하는 일 | 어디서 오는가 |
|---|---|---|
| `kvm-modules` | 호스트 커널에 KVM·vhost 모듈을 올리고 끝납니다 | 이 저장소 |
| `device` | Android 가상 기기 한 대(Cuttlefish, 720×1600). 켤 때마다 한국어·한국 시간·버튼 세 개짜리 바·한글 키보드로 맞춥니다 | Google의 cuttlefish-orchestration 이미지 + `device/entrypoint.sh` |
| `artemis` | 화면을 보고 다음 동작 하나를 고르는 서버 | [haebom-artemis](https://github.com/youth-hackathon/haebom-artemis) |
| `tts` | 안내 문장을 소리로 바꾸는 서버 | [haebom-tts](https://github.com/youth-hackathon/haebom-tts) |
| `front` | 검증된 매뉴얼로 먼저 답하고, 없으면 artemis로 넘기는 서버 | [haebom-manual](https://github.com/youth-hackathon/haebom-manual) |
| `api` | 시연 API. 기기를 준비하고, 페이지의 버튼을 기기 명령으로 바꾸고, 앱의 로그를 진행 기록으로 바꿉니다 | `api/` |
| `web` | 시연 페이지와 프록시(nginx). 비밀번호, https | `web/` |

기기에 설치되는 앱은 `app/haebom-debug.apk`입니다([haebom-app](https://github.com/youth-hackathon/haebom-app)을 빌드한 것). `api`가 기기에 앱이 없으면 설치하고, 기기가 다시 켜져도 접근성 서비스와 서버 주소를 다시 맞춥니다.

기기 안의 앱은 `127.0.0.1:8770`(안내)과 `127.0.0.1:8766`(TTS)을 봅니다. 이 주소는 `adb reverse`로 `api` 컨테이너에 닿고, `api`가 `front`와 `tts` 컨테이너로 이어 줍니다. 그래서 앱 설정이 어디서나 같습니다.

## 키

키는 저장소에 넣지 않습니다. 띄우는 곳마다 `secrets/` 폴더에 넣습니다(`.gitignore`에 들어 있습니다).

| 파일 | 내용 | 없으면 |
|---|---|---|
| `secrets/artemis.env` | haebom-artemis의 `relay/.env.example`과 같은 형식 | 매뉴얼에 있는 일만 안내됩니다. 그 밖의 일은 AI가 답하지 못합니다 |
| `secrets/tts.env` | `TTS_ENGINE=gemini`와 `GEMINI_API_KEY=...` | 기본 엔진(baseline)으로 읽습니다 |

다른 자리에 있는 파일을 쓰려면 `.env`의 `ARTEMIS_ENV`, `TTS_ENV`에 경로를 적습니다.

## 서버(VM)에 띄우기

호스트에 KVM이 있어야 합니다. 클라우드 VM이면 중첩 가상화를 켠 리눅스 VM(예: GCP `n2-standard-8` 이상, `--enable-nested-virtualization`), 내 컴퓨터면 Docker Desktop(WSL2)이나 리눅스의 Docker입니다.

```bash
git clone https://github.com/youth-hackathon/haebom-demo.git && cd haebom-demo
cp .env.example .env
# .env 에서:  DEMO_PASSWORD=<비밀번호>   WEB_BIND=0.0.0.0   WEBRTC_BIND=0.0.0.0
mkdir -p secrets && nano secrets/artemis.env
docker compose up -d --build
```

방화벽에서 열 포트는 `6080`(http), `6443`(https), `15550-15599`(tcp와 udp, WebRTC)입니다. 마이크까지 쓰려면 `https://<서버 주소>:6443/haebom/`으로 엽니다. 인증서는 자체 서명이라 브라우저가 경고를 한 번 보여 줍니다. 제대로 된 인증서가 있으면 `web` 서비스의 `/etc/nginx/tls`에 `cert.pem`, `key.pem`을 마운트합니다.

기기가 알려 주는 WebRTC 주소는 컨테이너 안의 주소라서, 페이지가 "이 페이지를 연 주소의 같은 포트"를 연결 후보로 하나 더 넣습니다(`web/www/tune.js`). 그래서 서버의 공인 주소를 따로 설정하지 않습니다.

## 자주 쓰는 명령

```bash
docker compose ps                       # device 가 healthy 면 기기가 켜진 것입니다
docker compose logs -f device           # 기기가 켜지는 과정
docker compose logs -f api              # 시연 API
docker compose build --no-cache front   # 매뉴얼을 새로 받아 다시 만들기 (haebom-manual 의 main)
docker compose down                     # 내리기. 기기 상태(볼륨)는 남습니다
docker compose down -v                  # 기기까지 지우기. 다음에 Android 이미지를 다시 받습니다
adb connect 127.0.0.1:6520              # 호스트에서 기기에 직접 붙기
```

## 시연 API

`web`의 `/haebom/api/` 아래에 있습니다. 밖에서 보낸 글자가 기기의 셸에 닿는 곳은 `start`의 `task` 하나이고, 길이를 제한하고 따옴표로 감싸 한 인자로만 넘깁니다. `reset`은 정해진 명령만 실행합니다.

| 요청 | 하는 일 |
|---|---|
| `GET state` | 기기·앱·서버가 준비됐는지, 이 기기에서 쓸 수 있는 매뉴얼 목록, 폰의 실제 값 |
| `GET events?after=<번호>&run=<번호>` | 안내 진행 기록. `after` 뒤에 바뀐 것만 |
| `POST start` `{"task": "글자 크기 키우기"}` | 안내 시작 |
| `POST stop` | 안내 멈춤 |
| `POST reset` | 처음 상태로: 쓰던 앱 끄기, 글자 크기 1.0, 알람 지우기, 홈 화면 |

## 확인한 것

Windows의 Docker Desktop(WSL2)에서 `docker compose up`으로 띄우고, 헤드리스 Chrome으로 페이지를 열어 확인했습니다(2026-11-21).

| 항목 | 확인한 방법 | 결과 |
|---|---|---|
| 기기 화면 | 페이지 안 영상의 크기와 WebRTC 통계 | 720×1600, 초당 56~58장 |
| 페이지에서 누르기 | 페이지의 기기 화면에서 전화 아이콘 자리를 누른 뒤 기기에 앞에 뜬 창을 물음 | `com.android.dialer` |
| 소리 | 안내를 시작해 기기가 첫 문장을 읽는 동안 브라우저가 받은 소리 패킷 | 0 → 279개, 문장이 끝나면 멈춤 |
| 마이크 | 마이크 켜기를 누른 뒤 브라우저가 기기로 보낸 소리 패킷(가짜 마이크 장치) | 2초에 100개씩 늘어남 |
| 안내 한 번 전체 | 페이지에서 "글자 크기 키우기"를 누르고 대역 사용자가 안내를 따라감 | 매뉴얼 5번, AI 0번, 기기의 `font_scale` 1.0 → 1.15 |
| 다른 일 | 페이지에서 "알람 8시에 설정하기"를 누르고 대역 사용자가 따라감 | 매뉴얼 8번, AI 0번, 기기의 알람 목록에 8:00 켜짐 |
| AI가 답하는 길 | 매뉴얼에 없는 요청 하나를 `front`에 보냄 | 8.3초 뒤 `meta.source`가 `model`인 답 |
| https 포트 | 같은 확인을 `https://127.0.0.1:6443`에서 | 같음 |
| 비밀번호 | `DEMO_PASSWORD`를 넣고 띄움 | 없이는 페이지·기기 화면·API 모두 401, 넣으면 화면과 소리·마이크까지 같음 |
| 이미지 빌드 | `artemis`, `tts`, `front`를 각 저장소의 main에서 빌드 | 됨 |

클라우드 VM에서는 아직 띄워 보지 않았습니다. 다른 컴퓨터의 브라우저에서 WebRTC가 붙는지(위의 "연결 후보를 하나 더 넣는" 부분)는 VM에서 확인해야 합니다.

## 이전 방식

`deploy/gcp/`에는 Docker 없이 GCP VM에 Cuttlefish를 직접 설치해 여러 대를 띄우던 스크립트가 남아 있습니다. 기기 여러 대를 한 VM에서 돌릴 때의 기록과 측정값이 거기 있습니다. 지금의 compose는 기기 한 대를 띄웁니다.
