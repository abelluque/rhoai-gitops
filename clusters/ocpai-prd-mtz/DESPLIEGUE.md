# Despliegue ocpai-prd-mtz

Correr como `cluster-admin`, parado en el clone de `https://github.com/surtecnologias/rhoai-gitops.git` rama `main`.

No correr `bootstrap/opentlc-root-app.yaml`.

Los nodos `infra01`, `infra02` e `infra03` tienen taint `node-role.kubernetes.io/infra=reserved:NoSchedule`. El overlay no tolera ese taint. El label de plataforma va en `worker01`, `worker02` y `worker03`.

```bash
oc whoami
oc get csv -n openshift-gitops

oc create secret generic rhoai-gitops-repo -n openshift-gitops \
  --from-literal=type=git \
  --from-literal=url=https://github.com/surtecnologias/rhoai-gitops.git \
  --from-literal=username=lebrizuela-sur \
  --from-literal=password='PEGAR_PAT_ACA'
oc label secret rhoai-gitops-repo -n openshift-gitops argocd.argoproj.io/secret-type=repository

oc label node worker01.ocpai-prd-mtz.intranet.local worker02.ocpai-prd-mtz.intranet.local worker03.ocpai-prd-mtz.intranet.local workload.rhoai.io/platform=true

oc label node worker-ai-01.ocpai-prd-mtz.intranet.local worker-ai-02.ocpai-prd-mtz.intranet.local nvidia.com/gpu.present=true

oc adm taint node worker-ai-01.ocpai-prd-mtz.intranet.local worker-ai-02.ocpai-prd-mtz.intranet.local nvidia.com/gpu=true:NoSchedule --overwrite

oc get storageclass
oc patch storageclass ntnx-block -p '{"metadata":{"annotations":{"storageclass.kubernetes.io/is-default-class":"true"}}}'

oc create namespace rhoai-model-registries --dry-run=client -o yaml | oc apply -f -
oc create secret generic model-registry-mysql -n rhoai-model-registries \
  --from-literal=database-name=modelregistry \
  --from-literal=database-user=mlmduser \
  --from-literal=database-password='PASSWORD' \
  --from-literal=database-root-password='ROOT_PASSWORD'
oc create secret generic model-registry-minio -n rhoai-model-registries \
  --from-literal=AWS_ACCESS_KEY_ID=minio \
  --from-literal=AWS_SECRET_ACCESS_KEY='PASSWORD' \
  --from-literal=AWS_S3_ENDPOINT=http://model-registry-minio.rhoai-model-registries.svc.cluster.local:9000 \
  --from-literal=AWS_S3_BUCKET=models \
  --from-literal=AWS_DEFAULT_REGION=us-east-1

oc create namespace ai-models --dry-run=client -o yaml | oc apply -f -
oc create secret generic hf-token -n ai-models --from-literal=HF_TOKEN='hf_...'

oc apply -f bootstrap/gitops-controller-cluster-admin.yaml
oc apply -f bootstrap/ocpai-prd-mtz-root-app.yaml
oc get applications.argoproj.io -n openshift-gitops -w
```

Cuando las Applications estén `Synced` y `Healthy`:

```bash
oc get applications.argoproj.io -n openshift-gitops
oc get datasciencecluster,dscinitialization -A
oc get gateway,route -n openshift-ingress
oc get llminferenceservice -n ai-models
oc get nodes -l nvidia.com/gpu.present=true -o custom-columns=NAME:.metadata.name,GPUs:.status.allocatable.nvidia\.com/gpu
MODEL=granite-3-0-8b-instruct ./scripts/probe-maas.sh
```
