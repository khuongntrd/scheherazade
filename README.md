# Scheherazade

A FastAPI service that wraps [VieNeu TTS v3 Turbo](https://huggingface.co/pnnbao-ump/VieNeu-TTS-v3-Turbo) — a Vietnamese neural text-to-speech model (48 kHz) — and exposes a simple HTTP API for synthesis. Inference runs in-process (ONNX on CPU, PyTorch on GPU). Audio files are stored in MinIO and returned as presigned URLs, or streamed directly depending on the request.

## Architecture

```
Client → cloudflared → synthesize (FastAPI :8000, in-process TTS)
                                  ↘ minio (storage :9000)
```

| Service | Image | Role |
|---|---|---|
| `synthesize` | local build | FastAPI wrapper with in-process VieNeu v3 Turbo inference, stores output to MinIO |
| `minio` | `minio/minio:latest` | S3-compatible object store for audio files |
| `minio-init` | `minio/mc:latest` | One-shot bucket initialiser |
| `cloudflared` | `cloudflare/cloudflared:latest` | Cloudflare Tunnel for secure external access |

## Requirements

- Docker with Compose v2

No GPU is required — v3 Turbo runs in real time on CPU via ONNX Runtime (int8). The model weights are downloaded from Hugging Face on first start and cached in the `huggingface_cache` volume.

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
  { "id": "Phạm Tuyên", "description": "Phạm Tuyên — Nam · Bắc · Phong cách tự nhiên" }
]
```

v3 Turbo ships 14 preset voices covering the North, Central, and South regions, e.g. `Phạm Tuyên`, `Đoan Trang`, `Trúc Ly`, `Minh Đức`, `Xuân Vĩnh`, `Ngọc Trân`.

### `POST /api/synthesize`

Synthesize speech from text.

**Request body:**

| Field | Type | Default | Description |
|---|---|---|---|
| `text` | string | required | Text to synthesize. Supports inline emotion tags: `[cười]` (laugh), `[thở dài]` (sigh), `[hắng giọng]` (clear throat) |
| `voice` | string | `Đoan Trang` | Preset voice ID |
| `style` | string | `tu_nhien` | Reading style: `tu_nhien` (natural), `tin_tuc` (news), `doc_truyen` (storytelling) |
| `emotion` | string | — | Legacy v2 field; `natural`/`news`/`storytelling` are mapped to the equivalent `style` |
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
  -d '{"text": "Xin chào thế giới", "voice": "Đoan Trang", "stream": false}'
```

## Configuration

All settings are passed as environment variables (or via `.env`):

| Variable | Default | Description |
|---|---|---|
| `API_KEY` | _(empty — auth disabled)_ | Key required in `X-API-Key` header for `/api/*` routes |
| `TTS_BACKEND` | `auto` | `onnx` (CPU), `pytorch` (GPU), or `auto` (picks by CUDA availability) |
| `TTS_PRECISION` | `int8` | ONNX/CPU backbone precision: `int8` (fast, small) or `fp32` (max quality) |
| `DEFAULT_VOICE` | `Đoan Trang` | Fallback voice if none supplied |
| `DEFAULT_STYLE` | `tu_nhien` | Fallback reading style if none supplied |
| `MINIO_ENDPOINT` | `minio:9000` | MinIO internal host:port |
| `MINIO_ACCESS_KEY` | `admin` | MinIO access key |
| `MINIO_SECRET_KEY` | `p@ssw0rd` | MinIO secret key |
| `MINIO_BUCKET` | `tts-output` | Bucket for audio output |
| `MINIO_SECURE` | `false` | Use TLS for internal MinIO connection |
| `MINIO_PUBLIC_URL` | _(empty — uses internal URL)_ | Public base URL for presigned links (e.g. `https://storage.example.com`) |
| `PRESIGNED_EXPIRY_HOURS` | `24` | Presigned URL TTL in hours |
