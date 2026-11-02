# Caché semántico de prompts y respuestas

El README del repositorio, `ARCHITECTURE.md`, `ARCHITECTURE_en.md` y los README de `clusters/opentlc` y `clusters/ocpai-prd-mtz` resumen esta capa. Este archivo es el que hay que seguir para cambiar una regla o probarla.

Este componente es la parte de caché de [Stop paying for the same prompt](https://www.redhat.com/en/blog/stop-paying-same-prompt-optimize-ai-costs-redis-red-hat-openshift) y del flujo de [LangCache](https://redis.io/customers/mangoes-ai/). No incluye el router semántico, los agentes, el dashboard ni la cola de trabajos del quickstart de Redis.

Redis guarda el embedding del prompt y la respuesta del modelo. Un prompt posterior, igual o parecido en significado, se responde desde Redis y no llama al LLM. El modelo de embeddings es `redis/langcache-embed-v2`, el que documenta RedisVL para este caché. La distancia es coseno de Redis: 0 es el mismo vector y 2 es el opuesto. Un umbral más bajo exige más parecido.

La Route `semantic-cache` queda delante de MaaS. Un acierto no llama al modelo. Un fallo reenvía el mismo `Authorization` al Gateway y Authorino sigue validando la key.

## Flujo

1. El cliente llama a la Route `semantic-cache` con el mismo cuerpo OpenAI de `/v1/chat/completions` y el mismo `Authorization` que usaría contra MaaS.
2. Si el modelo está apagado en la política, el pedido va directo a MaaS.
3. Si no, el servicio de embeddings calcula el vector del último mensaje `user`.
4. Redis busca el vecino más cercano con el mismo `model` y el mismo system prompt.
5. Si la distancia es menor o igual al umbral, devuelve la respuesta guardada. El header es `x-semantic-cache: hit` y `usage` queda en cero.
6. Si no hay acierto, reenvía a `https://<gateway>/ai-models/<model>/v1/chat/completions`. Guarda la respuesta con el TTL de la política. El header es `x-semantic-cache: miss`.

No se cachea, y el header dice por qué, cuando ocurre alguno de estos casos:

| Header `x-semantic-cache` | Motivo |
| --- | --- |
| `bypass` | El cliente mandó `x-semantic-cache: bypass` |
| `stream` | `stream: true`. La respuesta se reenvía tal cual |
| `temperature` | `temperature` es mayor que `max_temperature` |
| `disabled` | El modelo está en `enabled: false` |
| `pii` | El prompt parece un mail, un secreto, un CBU o un número largo. No se busca ni se guarda |
| `empty` | No hay mensaje `user` |

Dos system prompts distintos no comparten respuesta, aunque la pregunta sea la misma.

## Dónde se cambia la regla

El archivo es `base/policy.yaml`. Los overlays no lo copian: un cambio ahí vale para `ocpai-prd-mtz` y para `opentlc`.

```yaml
ttl_seconds: 86400
max_temperature: 0.2
models:
  granite-3-1-2b-instruct:
    enabled: true
    distance_threshold: 0.25
  qwen25-coder-32b:
    enabled: true
    distance_threshold: 0.10
```

| Campo | Efecto |
| --- | --- |
| `enabled` | `false` saca ese endpoint del caché. El pedido sigue llegando a MaaS por esta Route. |
| `distance_threshold` | Distancia máxima para considerar que dos prompts son el mismo. 0.10 pide casi el mismo texto. 0.25 acepta una paráfrasis. Subirlo de más devuelve una respuesta de otra pregunta. |
| `ttl_seconds` | Segundos que vive una entrada. `0` no expira. |
| `max_temperature` | Por encima de este valor no se lee ni se escribe el caché. |

Para apagar un modelo alcanza con `enabled: false`. Para encenderlo, `enabled: true` y un umbral. Un modelo que no está en la lista queda apagado.

En este branch están encendidos `granite-3-1-2b-instruct` (laboratorio, umbral 0.25), `qwen25-coder-32b` y `deepseek-coder-33b` (umbral 0.10). `granite-3-0-8b-instruct` queda apagado para poder probar el corte por modelo.

El host de MaaS no está en esa política. Está en el env `MAAS_GATEWAY_HOST` del Deployment `semantic-cache`:

- laboratorio: `maas.apps.cluster-zd9hr.zd9hr.sandbox1414.opentlc.com` en `overlays/opentlc/upstream.yaml`
- producción: `maas.apps.ocpai-prd-mtz.mtz.local` en `overlays/ocpai-prd-mtz/upstream.yaml`

`MAAS_TLS_VERIFY` queda en `false` en los dos clusters: el certificado de ingress no está en el trust store del contenedor.

## Qué se despliega

En el namespace `rhoai-semantic-cache`:

- Redis 8.2 con el motor de búsqueda vectorial, en el PVC `semantic-cache-redis` (10 Gi). Laboratorio: `gp3-csi`. Producción: `nutanix-files-dynamic`.
- `text-embeddings-inference` con `redis/langcache-embed-v2`.
- El proxy `semantic-cache`, que instala sus dependencias al arrancar e implementa `/v1/chat/completions`.

La Application `semantic-cache` apunta a `https://github.com/abelluque/rhoai-gitops.git`, branch `semantic-cache-demo-platform`. Las demás Applications del laboratorio siguen en `rhoai-maas-demo-platform` y las de producción siguen en `main`. Las dos Applications raíz de este branch leen el app-of-apps desde `semantic-cache-demo-platform`, así el caché entra en los dos clusters.

## Prueba

```bash
curl -sD - -o /tmp/out.json \
  "https://semantic-cache-rhoai-semantic-cache.apps.<cluster>/v1/chat/completions" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"model":"granite-3-1-2b-instruct","temperature":0,"messages":[{"role":"user","content":"¿Cuál es la política de devolución?"}]}'
```

En producción usar `qwen25-coder-32b` o `deepseek-coder-33b`. La primera respuesta trae `x-semantic-cache: miss`. Una paráfrasis dentro del umbral trae `x-semantic-cache: hit` y no consume GPU. `granite-3-0-8b-instruct` responde con `x-semantic-cache: disabled` y sigue hasta el modelo.

`GET /metrics` expone `semantic_cache_requests_total`.
