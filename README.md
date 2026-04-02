# KagerFlix — Video Streaming Platform

A full-featured video streaming platform built with **Python (Flask)**, **FFmpeg**, **AWS S3**, and **SQLite**. Upload, auto-transcode to HLS, and stream video with adaptive bitrate.

---

## Features

- **Video Upload** — Drag-and-drop with real-time progress bar (up to 500MB)
- **Auto Transcoding** — Background FFmpeg transcoding to HLS (360p / 720p / 1080p)
- **Adaptive Streaming** — HLS.js player auto-selects quality based on bandwidth
- **Direct Streaming** — Range-request byte-serving for MP4 fallback
- **Thumbnail Generation** — Auto-generated from frame at 2s via FFmpeg
- **AWS S3 Integration** — Optional cloud storage for HLS playlists
- **Dashboard** — Table view with status, views, resolution, size; inline edit & delete
- **Polling** — Watch page auto-refreshes when transcoding completes

---

## Prerequisites

```bash
# Install system dependencies
brew install ffmpeg          # macOS
sudo apt install ffmpeg      # Ubuntu/Debian
```

---

## Installation

```bash
cd video_platform
pip install -r requirements.txt
```

---

## Running

```bash
python app.py
# Server at http://localhost:5000
```

---

## AWS S3 (Optional)

Set environment variables to enable S3 upload:

```bash
export AWS_S3_BUCKET=your-bucket-name
export AWS_REGION=us-east-1
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
```

If not set, all files are stored locally in `uploads/` and `processed/`.

---

## Project Structure

```
video_platform/
├── app.py              # Flask app + all routes
├── database.py         # SQLAlchemy models (Video, User)
├── requirements.txt
├── uploads/            # Raw uploaded videos
├── processed/          # HLS segments + thumbnails
│   └── <video_id>/
│       ├── thumbnail.jpg
│       ├── stream.m3u8     # Master HLS playlist
│       ├── 360p/
│       ├── 720p/
│       └── 1080p/
└── templates/
    ├── base.html       # Shared layout + nav
    ├── index.html      # Discover page (video grid)
    ├── dashboard.html  # Admin dashboard (table)
    ├── upload.html     # Upload form + progress
    └── watch.html      # Video player + sidebar
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Discover page |
| GET | `/dashboard` | Management dashboard |
| GET/POST | `/upload` | Upload form / handle upload |
| GET | `/watch/<id>` | Watch page (increments views) |
| GET | `/stream/<id>/master.m3u8` | HLS master playlist |
| GET | `/stream/<id>/<quality>/index.m3u8` | Quality playlist |
| GET | `/stream/<id>/<quality>/<seg>` | TS segment |
| GET | `/stream/<id>/direct` | Direct MP4 range streaming |
| GET | `/thumbnail/<id>` | JPEG thumbnail |
| GET | `/api/video/<id>` | Video JSON |
| PATCH | `/api/video/<id>` | Update title/description |
| DELETE | `/api/video/<id>` | Delete video + files |
| GET | `/api/stats` | Global stats JSON |

---

## Tech Stack

- **Backend**: Python, Flask, Flask-SQLAlchemy
- **Database**: SQLite
- **Transcoding**: FFmpeg (HLS, thumbnails, metadata)
- **Storage**: Local filesystem + AWS S3 (optional)
- **Player**: HLS.js for adaptive streaming
- **Frontend**: Vanilla HTML/CSS/JS — no framework dependencies
