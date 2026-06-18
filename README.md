# Scheherazade

A FastAPI service that wraps [VieNeu TTS](https://huggingface.co/pnnbao-ump/VieNeu-TTS-v2) — a Vietnamese neural text-to-speech model — and exposes a simple HTTP API for synthesis. Audio files are stored in MinIO and returned as presigned URLs, or streamed directly depending on the request.

## Architecture

```
Client → cloudflared → synthesize (FastAPI :8000) → vieneu-tts (inference :23333)
                                                   ↘ minio (storage :9000)
```

| Service | Image | Role |
|---|---|---|
| `vieneu-tts` | `pnnbao/vieneu-tts:latest` | GPU inference engine (OpenAI-compatible API) |
| `synthesize` | local build | FastAPI wrapper, stores output to MinIO |
| `minio` | `minio/minio:latest` | S3-compatible object store for audio files |
| `minio-init` | `minio/mc:latest` | One-shot bucket initialiser |
| `cloudflared` | `cloudflare/cloudflared:latest` | Cloudflare Tunnel for secure external access |

## Requirements

- Docker with Compose v2
- NVIDIA GPU + [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)

## Quick Start

1. **Add your Cloudflare tunnel token** — paste it into `secrets/cloudflare_tunnel_token.txt` (get it from the Cloudflare Zero Trust dashboard under Tunnels).

2. **Create a `.env` file** in the project root:

```env
API_KEY=your-secret-key
MINIO_PUBLIC_URL=https://storage.your-domain.com   # optional, for public presigned URLs
```

3. **Start the stack:**

```bash
docker compose up --build
```

The API will be available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

MinIO console is available at `http://localhost:9001` (user: `admin`, password: `p@ssw0rd`).

## Authentication

All `/api/*` endpoints require an `X-API-Key` header. Set the key via the `API_KEY` environment variable. If `API_KEY` is empty, authentication is disabled.

```bash
curl -H "X-API-Key: your-secret-key" http://localhost:8000/api/voices
```

The `/health` endpoint is public and requires no key.

## API

### `GET /health`

Returns `{"status": "ok"}`. Used by Docker healthcheck.

### `GET /api/voices`

List available preset voices.

```json
[
  { "id": "Doan", "description": "..." }
]
```

### `POST /api/synthesize`

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
  "url": "https://storage.your-domain.com/tts-output/550e8400-e29b-41d4-a716-446655440000.wav?..."
}
```

**`stream: true`** — returns the WAV file as a streaming `audio/wav` response.

**Example:**

```bash
curl -X POST http://localhost:8000/api/synthesize \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-secret-key" \
  -d '{"text": "Xin chào thế giới", "voice": "Doan", "stream": false}'
```

## Configuration

All settings are passed as environment variables (or via `.env`):

| Variable | Default | Description |
|---|---|---|
| `API_KEY` | _(empty — auth disabled)_ | Key required in `X-API-Key` header for `/api/*` routes |
| `REMOTE_API_BASE` | `http://vieneu-tts:23333/v1` | VieNeu inference endpoint |
| `REMOTE_MODEL_ID` | `pnnbao-ump/VieNeu-TTS-v2` | Model identifier |
| `DEFAULT_VOICE` | `Doan` | Fallback voice if none supplied |
| `DEFAULT_EMOTION` | `natural` | Fallback emotion if none supplied |
| `MINIO_ENDPOINT` | `minio:9000` | MinIO internal host:port |
| `MINIO_ACCESS_KEY` | `admin` | MinIO access key |
| `MINIO_SECRET_KEY` | `p@ssw0rd` | MinIO secret key |
| `MINIO_BUCKET` | `tts-output` | Bucket for audio output |
| `MINIO_SECURE` | `false` | Use TLS for internal MinIO connection |
| `MINIO_PUBLIC_URL` | _(empty — uses internal URL)_ | Public base URL for presigned links (e.g. `https://storage.example.com`) |
| `PRESIGNED_EXPIRY_HOURS` | `24` | Presigned URL TTL in hours |
