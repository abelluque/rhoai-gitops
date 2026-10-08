# Overlay ocpai-prd-mtz

Cluster de producción OpenShift 4.22. App-of-apps en `apps/`. Application raíz: `../../bootstrap/ocpai-prd-mtz-root-app.yaml`.

## Topología

| Rol | Cantidad | Hardware | Schedulable | Cargas |
| --- | --- | --- | --- | --- |
| Masters | 3 | VM, 12 vCPU / 64 Gi | No | Plano de control |
| Infra | 3 | VM, 16 vCPU / 64 Gi | Sí | Plataforma (`workload.rhoai.io/platform=true`) |
| Workers virtuales | 3 | VM, 12 vCPU / 32 Gi | Sí | Mismo label de plataforma |
| Workers GPU | 2 | SuperMicro SYS-521GE-TNRT, 128 vCPU / 1500 Gi, 6× NVIDIA H200 | Sí, taint GPU | Inferencia LLM |

Taint GPU: `nvidia.com/gpu=true:NoSchedule`. Host MaaS: `maas.apps.ocpai-prd-mtz.intranet.local`.

## Diferencias respecto al laboratorio

- Wave 2 incluye `nvidia-gpu-enablement` (NFD canal `stable` sin CSV pineado + NVIDIA GPU Operator). MIG `strategy: none`. El NVIDIA Network Operator ya corre en el cluster (puerto 400G Active, firmware 28.43.1014) y no se reinstala desde acá.
- Gateway API mediante Ingress Operator (`openshift-default`). **No** se instala Service Mesh 3.
- Wave 4 no despliega PostgreSQL in-cluster. Secret `maas-db-config` provisionado fuera de banda. Véase `secrets/`.
- PVCs sobre las clases que ya existen: MySQL en `ntnx-block` (RWO); MinIO, notebooks y pipelines en `ntnx-files` (RWX). No se crea `nutanix-files-dynamic`.
- Tres `LLMInferenceService` en GPU: `granite-3-0-8b-instruct`, `qwen25-coder-32b`, `deepseek-coder-33b`.
- HardwareProfiles `cpu-platform` y `gpu` (NVIDIA H200).

El procedimiento de arranque, la tabla de sync-waves y el diagrama de arquitectura están en el [README del repositorio](../../README.md).
