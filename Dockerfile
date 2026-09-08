FROM python:3.10-slim

# FFmpeg ইন্সটল
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# HLS সেগমেন্ট স্টোর করার ডিরেক্টরি
RUN mkdir -p /app/hls

EXPOSE 8080

CMD ["python", "main.py"]
