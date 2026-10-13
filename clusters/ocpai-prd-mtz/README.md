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
- RHCL sigue el canal `stable` sin `startingCSV`. En OpenShift 4.22 el catálogo resuelve `rhcl-operator.v1.4.3`; `v1.3.4` no está. El salto de minor puede cambiar CRDs de AuthPolicy y TokenRateLimitPolicy.
- Gateway API mediante Ingress Operator (`openshift-default`). **No** se instala Service Mesh 3.
- Wave 4 despliega PostgreSQL in-cluster en `redhat-ods-applications` (el mismo base del laboratorio). PVC `postgresql` de 5 Gi en `ntnx-block`. El Job `create-maas-db-config` crea el Secret `maas-db-config`.
- PVCs sobre las clases que ya existen: MySQL en `ntnx-block` (RWO); MinIO, notebooks y pipelines en `ntnx-files` (RWX). No se crea `nutanix-files-dynamic`.
- El Model Registry sigue con el Deployment, el Secret y el endpoint de Abel. `quay.io/minio/minio` dejó de ser público el 24 de septiembre de 2026. La imagen que corre es Silo, copiada al registry interno del cluster (`rhoai-model-registries/silo`). Mismas variables `MINIO_ROOT_*`, mismo `server /data` y mismo PVC. No es una imagen de Red Hat.
- Tres `LLMInferenceService` en GPU: `granite-3-0-8b-instruct`, `qwen25-coder-32b`, `deepseek-coder-33b`.
- HardwareProfiles `cpu-platform` y `gpu` (NVIDIA H200).

El procedimiento de arranque, la tabla de sync-waves y el diagrama de arquitectura están en el [README del repositorio](../../README.md).
