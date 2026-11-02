"""OpenAI-compatible semantic cache in front of MaaS.

Redis stores the prompt embedding and the model response. A later prompt whose
embedding is within the configured cosine distance returns that response and
does not call the LLM. This is the self-hosted form of the LangCache flow
described by Redis and the Red Hat OpenShift semantic-cache architecture.
There is no semantic router and no agent.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import struct
import threading
import time
from collections import defaultdict
from typing import Any

import httpx
import yaml
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from redis import Redis
from redis.commands.search.field import NumericField, TagField, TextField, VectorField
from redis.commands.search.index_definition import IndexDefinition, IndexType
from redis.commands.search.query import Query

POLICY_PATH = os.environ.get("POLICY_PATH", "/etc/semantic-cache/policy.yaml")
REDIS_URL = os.environ.get("REDIS_URL", "redis://semantic-cache-redis:6379/0")
EMBED_URL = os.environ.get("EMBED_URL", "http://semantic-cache-embed:8080/embed")
MAAS_GATEWAY_HOST = os.environ["MAAS_GATEWAY_HOST"]
MAAS_TLS_VERIFY = os.environ.get("MAAS_TLS_VERIFY", "true").lower() != "false"
INDEX = "llmcache"
PREFIX = "llmcache:"

PII = re.compile(
    r"(?i)("
    r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}"
    r"|bearer\s+[a-z0-9._\-]{8,}"
    r"|(token|password|passwd|api[_-]?key|secret|cbu|cvv)\s*[:=]"
    r"|\b\d{16,}\b"
    r")"
)

app = FastAPI()
redis: Redis | None = None
index_ready = False
index_lock = threading.Lock()
vector_dim: int | None = None
counts: dict[str, int] = defaultdict(int)


def load_policy() -> dict[str, Any]:
    with open(POLICY_PATH, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def model_rule(policy: dict[str, Any], model: str) -> dict[str, Any]:
    rules = policy.get("models") or {}
    rule = rules.get(model) or {}
    return {
        "enabled": bool(rule.get("enabled", False)),
        "distance_threshold": float(rule.get("distance_threshold", 0.1)),
    }


def user_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = [
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") in (None, "text")
            ]
            return "\n".join(part for part in parts if part).strip()
    return ""


def system_fingerprint(messages: list[dict[str, Any]]) -> str:
    chunks = []
    for message in messages:
        if message.get("role") != "system":
            continue
        content = message.get("content")
        chunks.append(content if isinstance(content, str) else json.dumps(content, sort_keys=True))
    raw = "\n".join(chunks).strip()
    if not raw:
        return "none"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def tag(value: str) -> str:
    escaped = []
    for char in value:
        if char in r" ,.<>{}[]\"':;!@#$%^&*()-+=~|/\\":
            escaped.append("\\")
        escaped.append(char)
    return "".join(escaped)


def embed(text: str) -> list[float]:
    response = httpx.post(EMBED_URL, json={"inputs": text}, timeout=60)
    response.raise_for_status()
    body = response.json()
    vector = body[0] if body and isinstance(body[0], list) else body
    if not isinstance(vector, list) or not vector:
        raise RuntimeError("el modelo de embeddings no devolvió un vector")
    return [float(item) for item in vector]


def pack(vector: list[float]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def ensure_index(client: Redis, dim: int) -> None:
    global index_ready, vector_dim
    with index_lock:
        if index_ready and vector_dim == dim:
            return
        try:
            info = client.ft(INDEX).info()
            existing = int(info.get("vector_params_dim") or info.get(b"vector_params_dim") or 0)
        except Exception:
            existing = 0
        if existing and existing != dim:
            raise RuntimeError(
                f"el índice {INDEX} tiene dimensión {existing} y el modelo devolvió {dim}"
            )
        if not existing:
            try:
                client.ft(INDEX).create_index(
                    (
                        TextField("prompt"),
                        TextField("response"),
                        TagField("model"),
                        TagField("system_fp"),
                        NumericField("inserted_at"),
                        VectorField(
                            "prompt_vector",
                            "FLAT",
                            {"TYPE": "FLOAT32", "DIM": dim, "DISTANCE_METRIC": "COSINE"},
                        ),
                    ),
                    definition=IndexDefinition(prefix=[PREFIX], index_type=IndexType.HASH),
                )
            except Exception as exc:
                if "Index already exists" not in str(exc):
                    raise
        index_ready = True
        vector_dim = dim


def lookup(client: Redis, vector: list[float], model: str, system_fp: str, threshold: float) -> tuple[str, float] | None:
    query = (
        Query(f"(@model:{{{tag(model)}}} @system_fp:{{{tag(system_fp)}}})=>[KNN 1 @prompt_vector $vec AS dist]")
        .return_fields("response", "dist")
        .dialect(2)
    )
    found = client.ft(INDEX).search(query, query_params={"vec": pack(vector)})
    if not found.docs:
        return None
    raw_distance = found.docs[0].dist
    raw_response = found.docs[0].response
    if isinstance(raw_distance, bytes):
        raw_distance = raw_distance.decode()
    if isinstance(raw_response, bytes):
        raw_response = raw_response.decode()
    distance = float(raw_distance)
    if distance > threshold:
        return None
    return raw_response, distance


def store(
    client: Redis,
    prompt: str,
    answer: str,
    vector: list[float],
    model: str,
    system_fp: str,
    ttl: int,
) -> None:
    digest = hashlib.sha256(f"{model}\0{system_fp}\0{prompt}".encode()).hexdigest()
    key = f"{PREFIX}{digest}"
    client.hset(
        key,
        mapping={
            "prompt": prompt,
            "response": answer,
            "model": model,
            "system_fp": system_fp,
            "inserted_at": int(time.time()),
            "prompt_vector": pack(vector),
        },
    )
    if ttl > 0:
        client.expire(key, ttl)


def completion(model: str, content: str, distance: float | None) -> dict[str, Any]:
    body = {
        "id": f"chatcmpl-cache-{int(time.time())}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
    if distance is not None:
        body["semantic_cache"] = {"hit": True, "distance": distance}
    return body


def answer_text(payload: dict[str, Any]) -> str:
    try:
        return payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return ""


def mark(kind: str) -> None:
    counts[kind] += 1


@app.on_event("startup")
def startup() -> None:
    global redis
    redis = Redis.from_url(REDIS_URL, decode_responses=False)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    redis.ping()
    embed_health = EMBED_URL.removesuffix("/embed") + "/health"
    probe = httpx.get(embed_health, timeout=5)
    probe.raise_for_status()
    return {"status": "ok"}


@app.get("/metrics")
def metrics() -> PlainTextResponse:
    lines = [
        "# HELP semantic_cache_requests_total Decisiones del caché semántico.",
        "# TYPE semantic_cache_requests_total counter",
    ]
    for kind, value in sorted(counts.items()):
        lines.append(f'semantic_cache_requests_total{{result="{kind}"}} {value}')
    return PlainTextResponse("\n".join(lines) + "\n")


@app.post("/v1/chat/completions")
async def chat(request: Request) -> Response:
    payload = await request.json()
    model = str(payload.get("model") or "")
    messages = payload.get("messages") or []
    policy = load_policy()
    rule = model_rule(policy, model)
    prompt = user_text(messages)
    header = request.headers.get("x-semantic-cache", "").lower()
    temperature = payload.get("temperature")
    too_hot = temperature is not None and float(temperature) > float(policy.get("max_temperature", 0.2))
    bypass = (
        header == "bypass"
        or bool(payload.get("stream"))
        or too_hot
        or not rule["enabled"]
        or not prompt
        or bool(PII.search(prompt))
    )
    if header == "bypass":
        reason = "bypass"
    elif payload.get("stream"):
        reason = "stream"
    elif too_hot:
        reason = "temperature"
    elif not rule["enabled"]:
        reason = "disabled"
    elif not prompt:
        reason = "empty"
    elif PII.search(prompt):
        reason = "pii"
    else:
        reason = ""

    if not bypass:
        system_fp = system_fingerprint(messages)
        try:
            vector = embed(prompt)
            ensure_index(redis, len(vector))
            hit = lookup(redis, vector, model, system_fp, rule["distance_threshold"])
        except Exception as exc:
            mark("error")
            forwarded = await forward(request, payload, model)
            forwarded.headers["x-semantic-cache"] = "error"
            forwarded.headers["x-semantic-cache-error"] = str(exc)[:180]
            return forwarded
        if hit:
            text, distance = hit
            mark("hit")
            return JSONResponse(
                completion(model, text, distance),
                headers={
                    "x-semantic-cache": "hit",
                    "x-semantic-cache-distance": f"{distance:.4f}",
                },
            )
        forwarded = await forward(request, payload, model)
        if forwarded.status_code == 200:
            try:
                body = json.loads(forwarded.body)
                text = answer_text(body)
                if text and not PII.search(text):
                    store(
                        redis,
                        prompt,
                        text,
                        vector,
                        model,
                        system_fp,
                        int(policy.get("ttl_seconds") or 0),
                    )
            except Exception:
                mark("store-error")
        mark("miss")
        forwarded.headers["x-semantic-cache"] = "miss"
        return forwarded

    mark(reason or "bypass")
    forwarded = await forward(request, payload, model)
    forwarded.headers["x-semantic-cache"] = reason or "bypass"
    return forwarded


async def forward(request: Request, payload: dict[str, Any], model: str) -> Response:
    url = f"https://{MAAS_GATEWAY_HOST}/ai-models/{model}/v1/chat/completions"
    headers = {"content-type": "application/json"}
    if authorization := request.headers.get("authorization"):
        headers["authorization"] = authorization
    async with httpx.AsyncClient(verify=MAAS_TLS_VERIFY, timeout=180) as client:
        upstream = await client.post(url, headers=headers, json=payload)
    media = upstream.headers.get("content-type", "application/json")
    return Response(content=upstream.content, status_code=upstream.status_code, media_type=media)
