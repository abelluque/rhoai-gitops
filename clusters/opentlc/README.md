# Overlay OpenTLC

Cluster de laboratorio. App-of-apps en `apps/`. Application raíz: `../../bootstrap/opentlc-root-app.yaml`.

Inferencia CPU: `granite-3-1-2b-instruct` (SLM). PostgreSQL MaaS in-cluster. Sin NVIDIA GPU Operator y sin Service Mesh 3. Gateway API mediante Ingress Operator.

Host MaaS: `maas.apps.cluster-6f7dh.6f7dh.sandbox3519.opentlc.com`.

Wave 7 agrega `semantic-cache` en `rhoai-semantic-cache`. El único modelo del laboratorio, `granite-3-1-2b-instruct`, tiene el caché semántico encendido con distancia 0.25. La Route es aparte del Gateway MaaS. Redis no fija StorageClass y usa la default del sandbox. El TLS hacia el hostname de OpenTLC no se verifica (`MAAS_TLS_VERIFY=false`). Reglas y prueba: [components/semantic-cache/README.md](../../components/semantic-cache/README.md).

El procedimiento de arranque y la tabla de sync-waves están en el [README del repositorio](../../README.md).
