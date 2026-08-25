# RHOAI 3.4 + MaaS — GitOps (Kustomize + OpenShift GitOps)

Instalación de la misma pila que [rhoai-helm](https://github.com/abelluque/rhoai-helm) usando **Kustomize** y **OpenShift GitOps** (Argo CD) con el patrón **apps-of-apps**.

El Helm de origen sigue en `/Users/aluque/Developer/rhoai-helm`. Este repo **no** vive dentro de `rhoai-helm`. Regenerar bases:

```bash
HELM_ROOT=/Users/aluque/Developer/rhoai-helm ./hack/import-from-helm.sh
```

## Layout

```
rhoai-gitops/
├── bootstrap/opentlc-root-app.yaml   # Application raíz (se aplica una vez)
├── clusters/opentlc/apps/            # App-of-apps: AppProject + Applications
├── components/<app>/base             # Manifiestos Kustomize (render Helm)
│   └── overlays/opentlc              # Overlay de laboratorio
└── hack/                             # Reimportar desde Helm
```

## Waves (sync-wave de Argo CD)

| Wave | Application                 | Destino                     | Equiv. Helm              |
| ---- | --------------------------- | --------------------------- | ------------------------ |
| 1    | `cert-manager`              | `cert-manager-operator`     | wave 1                   |
| 1    | `observability-operators`   | `openshift-operators`       | wave 1                   |
| 1    | `platform-addons`           | `rhoai-model-registries`    | wave 1                   |
| 2    | `leaderworkerset`           | `openshift-lws-operator`    | wave 2                   |
| 2    | `rhcl`                      | `kuadrant-system`           | wave 2                   |
| 3    | `gateway-api`               | `openshift-ingress`         | wave 3                   |
| 4    | `maas-postgres`             | `redhat-ods-applications`   | wave 4                   |
| 5    | `openshift-ai`              | `redhat-ods-operator`       | wave 5                   |
| 6    | `llmisvc-granite`           | `ai-models`                 | wave 8 (CPU SLM)         |
| 7    | `maas-subscriptions`        | `models-as-a-service`       | wave 7                   |

No se incluye `nvidia-gpu-enablement` ni `service-mesh-operators` en OpenTLC.

Jobs que en Helm eran `post-install` hooks se anotaron como `argocd.argoproj.io/hook: PostSync`.

## Overlay OpenTLC

Laboratorio CPU (`cluster-6f7dh`): Gateway ClusterIP `:443` + Route **reencrypt** (mismo patrón que `data-science-gateway`). Granite 3.1 2B Instruct con `VLLM_CPU_KVCACHE_SPACE=4`. Postgres in-cluster (`opentlc-lab` es solo lab).

## Bootstrap

1. OpenShift GitOps ya debe existir (`openshift-gitops`). Si el cluster está vacío, instalá el operador GitOps **antes** del root app (o aplicá a mano `components/platform-addons` una vez).
2. Empujá este repo a Git y reemplazá `https://github.com/abelluque/rhoai-gitops.git` en:
   - `bootstrap/opentlc-root-app.yaml`
   - `clusters/opentlc/apps/appproject.yaml`
   - `clusters/opentlc/apps/*.yaml` (`spec.source.repoURL`)
3. Aplicá la Application raíz:

```bash
oc apply -f bootstrap/opentlc-root-app.yaml
oc -n openshift-gitops get applications.argoproj.io
```

Argo CD crea el `AppProject` `rhoai` y las Applications hijas. Las waves 1→7 ordenan el sync.

4. Esperá CSV `Succeeded` y Jobs `PostSync` (Kuadrant, DSCI/DSC, `create-maas-db-config`).

```bash
oc get applications.argoproj.io -n openshift-gitops
oc get datasciencecluster,dscinitialization -A
oc get gateway,route -n openshift-ingress
oc get llminferenceservice -n ai-models
```

Probe MaaS (token `oc`):

```bash
./scripts/probe-maas.sh
```

## Producción (`ocpai-prd-mtz`)

El overlay de producción **no** está renderizado todavía (GPU, tres modelos, Postgres externo). Ver [clusters/ocpai-prd-mtz/README.md](clusters/ocpai-prd-mtz/README.md).

## Notas

- `CreateNamespace=true` y `ServerSideApply=true` en las Applications hijas (OLM / CRDs).
- `prune: false` al inicio para no borrar Namespaces de plataforma si se desincroniza.
- Helm lookup (NS/OG preexistentes) no aplica aquí: GitOps declara el estado deseado. Si el NS ya existe, Argo lo adopta.
- Regenerar desde Helm **sobrescribe** `components/*/base`. No edites a mano lo que va a reimportarse; usá overlays.
