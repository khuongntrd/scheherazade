import os
import tempfile
import uuid
from datetime import timedelta
from urllib.parse import urlparse

import requests
from lxml import etree
from fastapi import FastAPI, HTTPException, Security
from fastapi.security import APIKeyHeader
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator
from typing import Optional
from minio import Minio

from vieneu import Vieneu

REMOTE_API_BASE = os.getenv("REMOTE_API_BASE", "http://100.93.85.78:23333/v1")
REMOTE_MODEL_ID = os.getenv("REMOTE_MODEL_ID", "pnnbao-ump/VieNeu-TTS-v2")
DEFAULT_EMOTION = os.getenv("DEFAULT_EMOTION", "natural")
DEFAULT_VOICE = os.getenv("DEFAULT_VOICE", "Doan")

API_KEY = os.getenv("API_KEY", "")

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "admin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "p@ssw0rd")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "tts-output")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"
MINIO_PUBLIC_URL = os.getenv("MINIO_PUBLIC_URL", "").rstrip("/")
PRESIGNED_EXPIRY_HOURS = int(os.getenv("PRESIGNED_EXPIRY_HOURS", "24"))

app = FastAPI(title="VieNeu TTS API")

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(key: str = Security(_api_key_header)):
    if not API_KEY:
        return
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

tts = Vieneu(
    mode="remote",
    api_base=REMOTE_API_BASE,
    model_name=REMOTE_MODEL_ID,
    emotion=DEFAULT_EMOTION,
    codec_repo="neuphonic/neucodec-onnx-decoder-int8",
)

minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=MINIO_SECURE,
)

if MINIO_PUBLIC_URL:
    _parsed = urlparse(MINIO_PUBLIC_URL)
    minio_presign_client = Minio(
        _parsed.netloc,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=_parsed.scheme == "https",
    )
else:
    minio_presign_client = minio_client


def ensure_bucket():
    if not minio_client.bucket_exists(MINIO_BUCKET):
        minio_client.make_bucket(MINIO_BUCKET)


def fetch_text_via_xpath(url: str, xpath: str) -> str:
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
    except requests.RequestException as e:
        raise HTTPException(status_code=422, detail=f"Failed to fetch URL: {e}")

    encoding = resp.encoding or "utf-8"
    parser = etree.HTMLParser(encoding=encoding)
    tree = etree.fromstring(resp.content, parser)
    nodes = tree.xpath(xpath)
    if not nodes:
        raise HTTPException(status_code=422, detail=f"XPath '{xpath}' matched no elements")

    parts = []
    for node in nodes:
        if isinstance(node, str):
            parts.append(node.strip())
        else:
            parts.append(" ".join(node.itertext()).strip())
    text = " ".join(" ".join(p.split()) for p in parts if p)
    if not text:
        raise HTTPException(status_code=422, detail="XPath matched elements but extracted no text")
    return text


class SynthesizeRequest(BaseModel):
    text: Optional[str] = None
    link: Optional[str] = None
    xpath: Optional[str] = None
    voice: Optional[str] = None
    emotion: Optional[str] = None
    stream: bool = False
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    @model_validator(mode="after")
    def check_text_source(self):
        has_link = bool(self.link)
        has_xpath = bool(self.xpath)
        has_text = bool(self.text)
        if has_link != has_xpath:
            raise ValueError("'link' and 'xpath' must be provided together")
        if not has_text and not has_link:
            raise ValueError("Provide either 'text' or both 'link' and 'xpath'")
        return self


@app.get("/health")
def health():
    return {"status": "ok"}


class ExtractRequest(BaseModel):
    link: str
    xpath: str


@app.post("/api/extract", dependencies=[Security(require_api_key)])
def extract(req: ExtractRequest):
    text = fetch_text_via_xpath(req.link, req.xpath)
    return {"link": req.link, "xpath": req.xpath, "text": text}


@app.get("/api/voices", dependencies=[Security(require_api_key)])
def list_voices():
    voices = tts.list_preset_voices()
    return [{"description": desc, "id": name} for desc, name in voices]


@app.post("/api/synthesize", dependencies=[Security(require_api_key)])
def synthesize(req: SynthesizeRequest):
    text = req.text or fetch_text_via_xpath(req.link, req.xpath)
    voice_id = req.voice or DEFAULT_VOICE
    try:
        voice_data = tts.get_preset_voice(voice_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Voice '{voice_id}' not found: {e}")

    infer_kwargs = {}
    if req.emotion:
        infer_kwargs["emotion"] = req.emotion

    try:
        audio = tts.infer(text=text, voice=voice_data, **infer_kwargs)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Inference failed: {e}")

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp_path = tmp.name
    tmp.close()
    tts.save(audio, tmp_path)

    if req.stream:
        def iterfile():
            with open(tmp_path, "rb") as f:
                yield from iter(lambda: f.read(8192), b"")
            os.unlink(tmp_path)

        return StreamingResponse(iterfile(), media_type="audio/wav")

    object_name = f"{req.correlation_id}.wav"
    try:
        ensure_bucket()
        minio_client.fput_object(
            MINIO_BUCKET,
            object_name,
            tmp_path,
            content_type="audio/wav",
        )
    except Exception as e:
        os.unlink(tmp_path)
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    url = minio_presign_client.presigned_get_object(
        MINIO_BUCKET,
        object_name,
        expires=timedelta(hours=PRESIGNED_EXPIRY_HOURS),
    )

    return {"correlation_id": req.correlation_id, "url": url}
