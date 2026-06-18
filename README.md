# Scheherazade

A FastAPI service that wraps [VieNeu TTS](https://huggingface.co/pnnbao-ump/VieNeu-TTS-v2) — a Vietnamese neural text-to-speech model — and exposes a simple HTTP API for synthesis. Audio files are stored in MinIO and returned as presigned URLs, or streamed directly depending on the request.

## Architecture

```
Client → synthesize (FastAPI :8000) → vieneu-tts (inference :23333)
                                    ↘ minio (storage :9000)
```

| Service | Image | Role |
|---|---|---|
| `vieneu-tts` | `pnnbao/vieneu-tts:latest` | GPU inference engine (OpenAI-compatible API) |
| `synthesize` | local build | FastAPI wrapper, stores output to MinIO |
| `minio` | `minio/minio:latest` | S3-compatible object store for audio files |
| `minio-init` | `minio/mc:latest` | One-shot bucket initialiser |

## Requirements

- Docker with Compose v2
- NVIDIA GPU + [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)

## Quick Start

```bash
docker compose up --build
```

The API will be available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

MinIO console is available at `http://localhost:9001` (user: `admin`, password: `p@ssw0rd`).

## API

### `GET /voices`

List available preset voices.

```json
[
  { "id": "Doan", "description": "..." },
  ...
]
```

### `POST /synthesize`

Synthesize speech from text.

**Request body:**

| Field | Type | Default | Description |
|---|---|---|---|
| `text` | string | required | Text to synthesize |
| `voice` | string | `Doan` | Preset voice ID |
| `emotion` | string | `natural` | Emotion tag |
| `stream` | bool | `false` | Stream WAV bytes directly instead of uploading |
| `correlation_id` | string | auto (UUID v4) | Client-supplied trace ID; used as the object name in MinIO |

**`stream: false` (default)** — uploads the WAV to MinIO, returns a presigned URL valid for 24 hours:

```json
{
  "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
  "url": "http://localhost:9000/tts-output/550e8400-e29b-41d4-a716-446655440000.wav?..."
}
```

**`stream: true`** — returns the WAV file as a streaming `audio/wav` response.

**Example:**

```bash
curl -X POST http://localhost:8000/synthesize \
  -H "Content-Type: application/json" \
  -d '{"text": "Xin chào thế giới", "voice": "Doan", "stream": false}'
```

## Configuration

All settings are passed as environment variables:

| Variable | Default | Description |
|---|---|---|
| `REMOTE_API_BASE` | `http://vieneu-tts:23333/v1` | VieNeu inference endpoint |
| `REMOTE_MODEL_ID` | `pnnbao-ump/VieNeu-TTS-v2` | Model identifier |
| `DEFAULT_VOICE` | `Doan` | Fallback voice if none supplied |
| `DEFAULT_EMOTION` | `natural` | Fallback emotion if none supplied |
| `MINIO_ENDPOINT` | `minio:9000` | MinIO host:port |
| `MINIO_ACCESS_KEY` | `admin` | MinIO access key |
| `MINIO_SECRET_KEY` | `p@ssw0rd` | MinIO secret key |
| `MINIO_BUCKET` | `tts-output` | Bucket for audio output |
| `MINIO_SECURE` | `false` | Use TLS for MinIO connection |
| `PRESIGNED_EXPIRY_HOURS` | `24` | Presigned URL TTL in hours |
