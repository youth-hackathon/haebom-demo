# 시연 API. 파이썬 표준 라이브러리와 adb만 씁니다. 기기에 설치할 앱(APK)이 같이 들어갑니다.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends adb && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY api/api.py /app/api.py
COPY app/haebom-debug.apk /app/haebom.apk
ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1
CMD ["python", "/app/api.py"]
