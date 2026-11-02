# Caché de prefijos y `prefix-cache-scorer`

Este documento describe el mecanismo que usa el branch `surtecnologias` para solicitudes idénticas o repetitivas, y cómo cambiar esas reglas. Sigue la documentación de Red Hat OpenShift AI Self-Managed 3.4:

- [Configuring scheduler settings for LLM inference services](https://docs.redhat.com/en/documentation/red_hat_openshift_ai_self-managed/3.4/html/deploy_models_using_distributed_inference_with_llm-d/configuring-llm-scheduler)
- [vLLM arguments reference](https://docs.redhat.com/en/documentation/red_hat_openshift_ai_self-managed/3.4/html/deploy_models_using_distributed_inference_with_llm-d/ref-vllm-arguments_distributed-inference)

Hay dos piezas, y las dos tienen que coincidir. El scheduler decide **a qué réplica** va el pedido. vLLM decide **si reutiliza el prefill** de ese prefijo.

OpenShift AI 3.4 no documenta un caché del AI Gateway que guarde la respuesta HTTP y la devuelva sin pasar por el modelo. Un acierto evita recalcular los tokens del prompt que ya se vieron. Los tokens nuevos de la respuesta se generan igual.

Tampoco compara el significado del texto. "Similar" en esta documentación quiere decir **el mismo prefijo de tokens** (el comienzo del prompt tokenizado), no dos frases distintas que quieran decir lo mismo.

En este branch hay una segunda capa, el [caché semántico](components/semantic-cache/README.md). Esa sí compara el significado y puede devolver la respuesta guardada sin llamar a vLLM. Vive en otra Route (`semantic-cache`), no en el Gateway MaaS. Si el cliente llama directo a `maas.apps…`, este documento es el único caché que interviene. Si llama a la Route semántica y no hay acierto, el pedido sigue hasta aquí y el prefill se reutiliza igual. Las dos políticas se editan en sitios distintos: el `LLMInferenceService` para los prefijos, y `components/semantic-cache/base/policy.yaml` para las respuestas.

## Qué ocurre con un pedido

1. El cliente llama a `https://maas.apps.<cluster>.<baseDomain>/ai-models/<model>/v1/chat/completions`.
2. El Gateway MaaS autentica con Authorino y aplica la cuota de la suscripción. Esa parte no mira la caché.
3. La HTTPRoute entrega el pedido al InferencePool del `LLMInferenceService`, en el puerto 8000.
4. El Endpoint Picker (EPP) del scheduler llm-d carga el `EndpointPickerConfig` de **ese** servicio.
5. Para cada réplica lista, calcula un puntaje y elige la de mayor puntaje combinado.
6. vLLM, en la réplica elegida, busca bloques KV de ese prefijo. Si están, no rehace ese prefill y sigue con la generación.

El puntaje combinado es la suma del puntaje de cada plugin multiplicado por su `weight`. Con los pesos de este repo:

```text
puntaje = (puntaje de queue-scorer × 2) + (puntaje de prefix-cache-scorer × 3)
```

El peso 3 contra el peso 2 hace que, si una réplica ya tiene el prefijo, se prefiera esa réplica aunque otra tenga la cola un poco más corta. Red Hat documenta exactamente esta pareja como el perfil que prioriza la reutilización de KV por encima de un reparto parejo.

### `prefix-cache-scorer`

Mantiene un índice de los prefijos que cada réplica ya calculó. La detección del acierto es por hash de bloques de tokens, así que funciona en un cluster desconectado: no baja un tokenizer de internet.

Si el prompt nuevo empieza igual que uno ya visto en una réplica, esa réplica puntúa más alto. El caso típico es el autocompletado: el archivo o el system prompt se repiten y solo cambia el final.

Con una sola réplica el plugin no elige entre pods. El ahorro lo hace el flag de vLLM. Con dos réplicas, sin este plugin, el pedido puede caer en el pod que no tiene el prefijo y el prefill se repite.

### `queue-scorer`

Puntúa más alto a la réplica con la cola más corta. Evita que la afinidad de caché concentre todo el tráfico en un solo pod.

### vLLM

`--enable-prefix-caching` guarda los bloques KV del prompt y los reutiliza cuando el prefijo coincide. `--no-enable-prefix-caching` no guarda ni reutiliza esos bloques.

El flag vive en `VLLM_ADDITIONAL_ARGS` del contenedor `main`. El scheduler no enciende la caché del motor: si el scorer manda el pedido a la réplica correcta pero el motor tiene la caché apagada, el prefill se calcula de nuevo.

## Estado en este branch

La etiqueta `rhoai.io/prefix-cache` es solo documentación para `oc get` y para Git. El controlador no la lee. Lo que aplica es el `EndpointPickerConfig` y el argumento de vLLM.

| Endpoint | Caso de uso | Réplicas | Caché | Manifiesto |
| --- | --- | --- | --- | --- |
| `qwen25-coder-32b` | code, autocompletado | 2 | enabled | `components/llmisvc-qwen25-coder-32b/overlays/ocpai-prd-mtz/llminferenceservice-qwen25-coder-32b.yaml` |
| `deepseek-coder-33b` | code, autocompletado | 2 | enabled | `components/llmisvc-deepseek-coder-33b/overlays/ocpai-prd-mtz/llminferenceservice-deepseek-coder-33b.yaml` |
| `granite-3-1-2b-instruct` | chat de laboratorio | 1 | enabled | `components/llmisvc-granite/base/llminferenceservice-granite-3-1-2b-instruct.yaml` |
| `granite-3-0-8b-instruct` | chat general | 2 | disabled | `components/llmisvc-granite-8b/base/llminferenceservice-granite-3-0-8b-instruct.yaml` |
| `qwen25-72b` | chat general | 1 | disabled | `components/llmisvc-qwen25-72b/overlays/ocpai-prd-mtz/llminferenceservice-qwen25-72b.yaml` |

`granite-3-0-8b-instruct` se declara en el base. El overlay `ai-models-dev` reutiliza ese base, así que Dev queda apagado junto con producción. Para separarlos hace falta un patch solo en `components/llmisvc-granite-8b/overlays/ocpai-prd-mtz-dev/kustomization.yaml`.

No hay regla por verbo HTTP, por header ni por suscripción free o premium. El corte de este repo es el endpoint, que coincide con el caso de uso `opendatahub.io/genai-use-case`.

## Regla encendida

Es el bloque de Qwen2.5 Coder 32B y de los otros endpoints con `rhoai.io/prefix-cache: enabled`.

```yaml
metadata:
  labels:
    rhoai.io/prefix-cache: enabled
spec:
  router:
    scheduler:
      config:
        inline:
          apiVersion: inference.networking.x-k8s.io/v1alpha1
          kind: EndpointPickerConfig
          plugins:
            - type: prefix-cache-scorer
            - type: queue-scorer
          schedulingProfiles:
            - name: default
              plugins:
                - pluginRef: queue-scorer
                  weight: 2
                - pluginRef: prefix-cache-scorer
                  weight: 3
  template:
    containers:
      - name: main
        env:
          - name: VLLM_ADDITIONAL_ARGS
            value: >-
              --enable-prefix-caching
```

`plugins` declara qué plugins existen. `schedulingProfiles` dice cuáles participan en el perfil `default` y con qué peso. Un plugin listado arriba y ausente del perfil no puntúa.

El `value` de `VLLM_ADDITIONAL_ARGS` ya trae `--max-model-len` y el paralelo del modelo. Se agrega el flag al final. No se reemplaza la línea entera.

## Regla apagada

El perfil por defecto de la plataforma, el que queda si `scheduler` está vacío, ya usa `queue-scorer` en 2 y `prefix-cache-scorer` en 3. Borrar el bloque no apaga la caché. Hay que publicar un perfil que no nombre al scorer de prefijos, y apagar el motor.

```yaml
metadata:
  labels:
    rhoai.io/prefix-cache: disabled
spec:
  router:
    scheduler:
      config:
        inline:
          apiVersion: inference.networking.x-k8s.io/v1alpha1
          kind: EndpointPickerConfig
          plugins:
            - type: queue-scorer
          schedulingProfiles:
            - name: default
              plugins:
                - pluginRef: queue-scorer
                  weight: 2
  template:
    containers:
      - name: main
        env:
          - name: VLLM_ADDITIONAL_ARGS
            value: >-
              --no-enable-prefix-caching
```

## Cómo cambiar las reglas

Cada cambio es un edit del `LLMInferenceService` de ese endpoint y un sync de su Application. No hace falta tocar el Gateway, Authorino ni las suscripciones MaaS.

### Encender un endpoint que está apagado

1. Poner la etiqueta `rhoai.io/prefix-cache: enabled`.
2. Reemplazar el `scheduler` por el bloque encendido de arriba.
3. Cambiar `--no-enable-prefix-caching` por `--enable-prefix-caching` en `VLLM_ADDITIONAL_ARGS`.
4. Sincronizar la Application de ese modelo.

### Apagar un endpoint que está encendido

1. Poner la etiqueta `rhoai.io/prefix-cache: disabled`.
2. Dejar el `scheduler` solo con `queue-scorer`, como en el bloque apagado.
3. Poner `--no-enable-prefix-caching`.
4. Sincronizar la Application.

Dejar `scheduler: {}` vuelve al default de la plataforma y la caché de enrutamiento queda prendida.

### Mover el equilibrio entre caché y cola

Se cambia solo el `weight` dentro de `schedulingProfiles`. Los dos plugins tienen que seguir existiendo en `plugins` y en el perfil.

| Cambio | Efecto |
| --- | --- |
| Subir el peso de `prefix-cache-scorer` (por ejemplo de 3 a 5) | Más afinidad: el prefijo repetido vuelve a la réplica caliente aunque su cola sea más larga. |
| Subir el peso de `queue-scorer` (por ejemplo de 2 a 5) | Más reparto: se evita el pod ocupado aunque otra réplica tenga el prefijo. |
| Peso 0 en un plugin | Ese plugin deja de influir. Para apagar la caché es más claro quitarlo del perfil, no dejarlo en 0. |

Red Hat documenta 2 y 3 como el punto de partida. Conviene no invertirlos salvo que una prueba muestre que la afinidad está saturando una réplica.

### Un modelo con una sola réplica

En `granite-3-1-2b-instruct` y `qwen25-72b` hay una réplica. El scorer no tiene otra a dónde mandar el pedido. El flag de vLLM sigue siendo el que evita repetir el prefill. El bloque del scheduler se deja igual para que, si más adelante se sube `replicas`, la afinidad ya esté definida.

### Granite 8B en Dev

`components/llmisvc-granite-8b/overlays/ocpai-prd-mtz-dev` incluye `../../base`. Un cambio de caché en el base aplica a `ai-models` y a `ai-models-dev`. Para que solo Dev cambie, el patch va en el `kustomization.yaml` de ese overlay, sobre el `LLMInferenceService` `granite-3-0-8b-instruct`, y no en el base.

## Cómo comprobarlo

Repetir dos veces el mismo prompt, con `temperature: 0`, contra el endpoint. La segunda llamada debe aumentar los aciertos solo donde la caché está encendida.

La tasa documentada por Red Hat:

```promql
sum(rate(vllm:prefix_cache_hits_total[5m]))
/
sum(rate(vllm:prefix_cache_queries_total[5m]))
```

Por pod:

```promql
sum by (pod) (rate(vllm:prefix_cache_hits_total[5m]))
/
sum by (pod) (rate(vllm:prefix_cache_queries_total[5m]))
```

En un endpoint apagado esa tasa queda en cero. Otras métricas del mismo capítulo de observabilidad: `inference_extension_prefix_indexer_size` y `inference_extension_prefix_indexer_hit_ratio`.

La latencia del segundo pedido baja en el prefill, el tiempo hasta el primer token. El cuerpo de la respuesta no sale de un almacén: el modelo lo vuelve a generar.
