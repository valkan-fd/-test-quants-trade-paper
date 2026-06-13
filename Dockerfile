FROM python:3.11-slim

WORKDIR /app

ARG GIT_HASH=unknown
ENV GIT_HASH=${GIT_HASH}

# システムパッケージ: rclone(GDrive同期用), curl 他
# rclone は Debian 公式 apt パッケージから導入(外部スクリプト実行を避ける)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    rclone \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# 依存導入
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ソースコード
COPY . .

# 作業ディレクトリ確保
RUN mkdir -p logs state results exports

# スケジューラー実行
CMD ["python", "scripts/daily_scheduler.py"]
