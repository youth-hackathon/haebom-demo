# GCP VM에서 Cuttlefish(Android 가상 기기)를 웹으로 보여 주기

웹 링크를 열면 Android 화면이 보이고 마우스와 키보드로 조작할 수 있습니다.
Google의 Cuttlefish를 KVM으로 돌리고, 내장 WebRTC 화면을 비밀번호를 건 nginx 뒤에 둡니다.

## 구성

| 무엇 | 어디 | 밖으로 여는가 |
|---|---|---|
| nginx (basic auth) | `0.0.0.0:6080` | 예 (TCP 6080-6089) |
| WebRTC 영상/입력 | UDP `15550-15599` | 예 (인증된 페이지에서 받은 정보가 있어야 연결됨) |
| Cuttlefish operator | `1080`(http), `1443`(https) | 아니오 (방화벽) |
| adb | `127.0.0.1:6520`, `6521`… | 아니오 |
| TTS 서버 | `127.0.0.1:8766` | 아니오 (직접은) |
| nginx → TTS | `0.0.0.0:6081`, 비밀 경로 | 예 (TCP 6080-6089 규칙 안) |

- VM: `haebom-emu`, `asia-northeast3-a`, `n2-standard-16`, Ubuntu 24.04, 디스크 100GB, 중첩 가상화 켬, 태그 `haebom-emu`
- 방화벽 규칙: `haebom-emu-web`(tcp:6080-6089), `haebom-emu-webrtc`(udp:15550-15599)
- 이미지: `aosp-android-latest-release/aosp_cf_x86_64_only_phone-userdebug` (받은 시점에 Android 17, API 37). Play 스토어와 Google Play 서비스는 없습니다.

## 처음부터 다시 만들기

1. VM과 방화벽 (gcloud가 되는 곳, 예: Cloud Shell)

   ```sh
   gcloud compute instances create haebom-emu --zone=asia-northeast3-a --machine-type=n2-standard-16 \
     --enable-nested-virtualization --image-family=ubuntu-2404-lts-amd64 --image-project=ubuntu-os-cloud \
     --boot-disk-size=100GB --boot-disk-type=pd-balanced --tags=haebom-emu \
     --metadata=ssh-keys="haebom:$(cat ~/.ssh/haebom_gcp.pub)"
   gcloud compute firewall-rules create haebom-emu-web --network=default --allow=tcp:6080-6089 \
     --target-tags=haebom-emu --source-ranges=0.0.0.0/0
   gcloud compute firewall-rules create haebom-emu-webrtc --network=default --allow=udp:15550-15599 \
     --target-tags=haebom-emu --source-ranges=0.0.0.0/0
   ```

2. 이 폴더를 VM에 올리고 차례로 실행 (`ssh haebom-emu`는 `~/.ssh/config`에 등록)

   ```sh
   ssh haebom-emu 'mkdir -p ~/haebom-src' && scp -r *.sh vm haebom-emu:~/haebom-src/
   ssh haebom-emu 'bash ~/haebom-src/10-cuttlefish-host.sh'      # Cuttlefish 호스트 패키지
   ssh haebom-emu 'mkdir -p ~/cf && cvd fetch --default_build=aosp-android-latest-release/aosp_cf_x86_64_only_phone-userdebug --target_directory=$HOME/cf'
   ssh haebom-emu 'bash ~/haebom-src/11-cuttlefish-web.sh'       # nginx + 비밀번호
   ssh haebom-emu 'bash ~/haebom-src/12-cuttlefish-service.sh && sudo systemctl start haebom-orchestrator haebom-cuttlefish haebom-watch'
   ```

## 쓰기

- 링크: `http://<VM 공개 IP>:6080/` (아이디 `haebom`). 기기 목록이 나오고 "열기"를 누르면 그 기기의 화면이 뜹니다. 기기 하나로 바로 가려면 `/devices/cvd_1-1-1/files/client.html`, `cvd_2-1-2`, `cvd_3-1-3`, `cvd_4-1-4`.
- 비밀번호: VM의 `~/.config/haebom/web-password.txt`. 바꾸려면 파일을 지우고 `11-cuttlefish-web.sh`를 다시 실행합니다.
- 기기 수: `~/.config/haebom/env`의 `HAEBOM_WARM`(부팅 때 만들 대수)과 `HAEBOM_MAX`(넘으면 가장 새것을 지움). 지금은 둘 다 4입니다. 바꾼 뒤 `sudo systemctl restart haebom-cuttlefish haebom-watch`.
- **VM이 다시 켜지면 기기를 새로 만듭니다. 기기 안의 데이터(설치한 앱 포함)는 남지 않습니다.** 앱 설치와 `adb reverse`는 부팅 뒤에 다시 해야 합니다.
- 기기 사양(CPU 4, 메모리 4GB, 720x1600): `vm/create.json`. 바꾸면 `11-cuttlefish-web.sh`를 다시 실행합니다.
- 손으로 만들고 지우기: `~/haebom/bin/haebom-cf.sh create | delete cvd_2 | list`
- 앱 설치: `~/cf/bin/adb -s 127.0.0.1:6520 install app.apk` (기기는 6520~6523)
- 서버 연결: `~/cf/bin/adb -s 127.0.0.1:6520 reverse tcp:8765 tcp:8765` (8766도 같음)
- VM 끄기: `gcloud compute instances stop haebom-emu --zone asia-northeast3-a`. 임시 IP라서 다시 켜면 주소가 바뀝니다.

## 서비스

| 서비스 | 하는 일 |
|---|---|
| `haebom-orchestrator` | Cuttlefish에 들어 있는 Host Orchestrator(`127.0.0.1:2080`). 기기를 만들고 지우는 API |
| `haebom-cuttlefish` | 부팅 때 지난 기기를 정리하고 `HAEBOM_WARM`대를 만듦 |
| `haebom-watch` | 새 기기에 한국어, 서울 시간대, 잠금 해제를 적용. `HAEBOM_MAX`를 넘으면 지움 |
| `nginx` | 비밀번호, 기기 목록 화면(`vm/www/index.html`), 프록시 |

## TTS 서버 (haebom-tts)

같은 VM의 `127.0.0.1:8766`에 Docker로 떠 있습니다. 닿는 길은 둘입니다.

- **밖의 폰**: `http://<VM 공개 IP>:6081/<비밀 경로>` 를 앱의 TTS 주소로 넣습니다. 앱이 뒤에 `/tts`를 붙입니다. 서버에 인증이 없어서 주소 안의 비밀 경로가 열쇠입니다. 틀리면 404입니다. 비밀 경로는 VM의 `~/.config/haebom/tts-token.txt`에 있고, `22-tts-public.sh`가 만듭니다.
- **VM 안의 Cuttlefish 기기**: `http://127.0.0.1:8766` (`haebom-watch`가 새 기기마다 `adb reverse` 8765, 8766을 자동으로 겁니다). 위의 공개 주소를 써도 됩니다.

`http`라서 주소(비밀 경로 포함)와 음성이 암호화되지 않고 오갑니다. 8766 포트 자체는 밖으로 열지 않습니다.

```sh
ssh haebom-emu 'bash ~/haebom-src/20-docker.sh'   # Docker Engine + compose
ssh haebom-emu 'bash ~/haebom-src/21-tts.sh'      # clone 또는 pull 뒤 다시 띄움
ssh haebom-emu 'bash ~/haebom-src/22-tts-public.sh'   # 6081 포트로 밖에 열기(비밀 경로)
```

- 위치: VM의 `~/haebom-tts`. 저장소 파일은 그대로 두고 `docker-compose.override.yml`(재시작 정책)만 덧붙였습니다.
- Gemini 쓰기: VM의 `~/haebom-tts/.env`에 `GEMINI_API_KEY=<키>`와 `TTS_ENGINE=gemini`를 적고 `21-tts.sh`를 다시 실행합니다. 키가 없으면 `baseline`(`espeak-ng`)으로 뜹니다.
- 확인: `curl http://127.0.0.1:8766/health`, `cd ~/haebom-tts && python3 check.py --no-bench`
- 로그: `sudo docker logs -f haebom-tts-tts-1`

## 요청이 올 때 기기를 만들기 (지금은 꺼 둠)

웹 화면의 "새 기기 만들기"와 "지우기" 버튼으로 기기를 늘리고 줄일 수 있게 만들어 두었고, 4대 고정으로 쓰기로 해서 막아 두었습니다. 다시 켜려면:

1. `vm/www/index.html`의 `DYNAMIC = false`를 `true`로
2. `vm/nginx/haebom-cuttlefish.conf`의 create, delete 위치에 있는 `return 403;` 두 줄을 지움
3. `HAEBOM_WARM`을 미리 띄울 대수로 낮추고 `11-cuttlefish-web.sh` 재실행

기기 한 대를 만드는 데 35초쯤, 한국어 설정까지 1분쯤 걸립니다.

## 재 본 값 (n2-standard-16, 기기당 vCPU 4 / 4GB)

VM 안의 브라우저로 잰 값(네트워크 제외, 720x1600): 눌러서 화면에 반응이 보이기까지 중앙값 78~81ms, 움직일 때 48~50fps. 1대일 때와 3대일 때가 같았습니다. 4대일 때는 재지 않았습니다. `bench/`에 측정 스크립트가 있습니다.

아래는 처음에 잰 값입니다.

| 해상도 | 대수 | 1분 부하 | 남은 메모리 | 설정 앱 여는 시간 | 스트리밍 |
|---|---|---|---|---|---|
| 1080x2400 | 1 | 0.7 | 57.5GB | 1.3초 | 약 15fps (버벅임) |
| 1080x2400 | 2 | 1.9 | 53.7GB | 1.2~1.3초 | |
| 1080x2400 | 3 | 3.5 | 49.5GB | 1.1~1.3초 | |
| 720x1600 | 3 | 2.5 | 50.1GB | 1.2초 | 약 34fps |

화면은 CPU로 그리고(`guest_swiftshader`) CPU로 인코딩합니다. 부드러움은 대수보다 해상도에 좌우됩니다.

## 안 될 때

- 기기가 안 뜸: `sudo journalctl -u haebom-cuttlefish -u haebom-orchestrator -n 50`, `cvd fleet`
- `failed to create a PCI root hub`: Ubuntu 24.04의 AppArmor가 crosvm의 샌드박스를 막는 것입니다. `sysctl kernel.apparmor_restrict_unprivileged_userns`가 0인지 봅니다(`12-cuttlefish-service.sh`가 설정).
- `Group is already running`: `cvd stop` 뒤 다시 시작. 그래도 안 되면 `cvd reset -y`(데이터 지워짐).
- 페이지는 뜨는데 화면이 안 나옴: UDP 15550-15599 방화벽 규칙과 VM의 태그를 봅니다.
- `/dev/kvm`이 없음: VM이 N2가 아니거나 중첩 가상화가 꺼져 있습니다.

## 그 밖의 파일

`01`~`04` 스크립트와 `vm/systemd/haebom-*@.service`는 처음에 만들던 공식 에뮬레이터 + noVNC 방식입니다. VM에 설치만 되어 있고 켜져 있지 않습니다. Play 스토어나 Google Play 서비스가 필요해지면 이쪽을 씁니다.
