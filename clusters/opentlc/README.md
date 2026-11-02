# Overlay OpenTLC

Cluster de laboratorio. App-of-apps en `apps/`. Application raíz: `../../bootstrap/opentlc-root-app.yaml`.

Inferencia CPU: `granite-3-1-2b-instruct` (SLM). PostgreSQL MaaS in-cluster. Sin NVIDIA GPU Operator y sin Service Mesh 3. Gateway API mediante Ingress Operator.

Host MaaS: `maas.apps.cluster-zd9hr.zd9hr.sandbox1414.opentlc.com`.

## Caché semántico

La Application `semantic-cache` (sync-wave 7) despliega Redis y el proxy en `rhoai-semantic-cache`. El modelo `granite-3-1-2b-instruct` queda encendido con umbral 0.25. La Route es `semantic-cache-rhoai-semantic-cache.apps.cluster-zd9hr.zd9hr.sandbox1414.opentlc.com`. El PVC usa `gp3-csi`. Cómo cambiar el umbral o apagar el modelo: [components/semantic-cache/README.md](../../components/semantic-cache/README.md).

El procedimiento de arranque y la tabla de sync-waves están en el [README del repositorio](../../README.md).
