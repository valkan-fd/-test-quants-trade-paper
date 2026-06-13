FROM python:3.11-slim

WORKDIR /app

# システムパッケージ: rclone, curl 他
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && curl https://rclone.org/install.sh | bash \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# 依存導入
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt apscheduler

# ソースコード
COPY . .

# 作業ディレクトリ確保
RUN mkdir -p logs state results exports

# スケジューラー実行
CMD ["python", "scripts/daily_scheduler.py"]
