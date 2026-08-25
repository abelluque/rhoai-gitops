# Overlay ocpai-prd-mtz (producción)

Aún no hay bases Kustomize. El origen Helm es `rhoai-helm/clusters/ocpai-prd-mtz`.

Diferencias vs OpenTLC a renderizar después:

- Wave 2: `nvidia-gpu-enablement` (NFD + GPU operator)
- Wave 3: Gateway; TLS de producción (Venafi o Route edge + secret)
- Wave 4: Postgres **externo** (`maas.postgres.deploy.enabled: false`) + Secret `maas-db-config`
- Wave 6: tres modelos GPU (`granite-3-0-8b-instruct`, `qwen25-coder-32b`, `deepseek-coder-33b`)
- No instalar SM3; Gateway API del Ingress Operator

Para generar: copiar `hack/import-from-helm.sh`, apuntar `CLUSTER` a `clusters/ocpai-prd-mtz` del repo Helm, y añadir Applications (wave NVIDIA = 2).
