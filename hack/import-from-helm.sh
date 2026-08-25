#!/usr/bin/env bash
# Re-render Kustomize component bases from the Helm source repo (rhoai-helm).
# Does not commit. Review the diff before applying.
set -euo pipefail

HELM_ROOT="${HELM_ROOT:-/Users/aluque/Developer/rhoai-helm}"
GITOPS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLUSTER="${CLUSTER:-${HELM_ROOT}/clusters/opentlc}"
CHARTS="${CHARTS:-${HELM_ROOT}/charts}"
OUT="${GITOPS_ROOT}/.rendered"

command -v helm >/dev/null || { echo "helm is required" >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }
[[ -d "${HELM_ROOT}/charts" ]] || { echo "HELM_ROOT=${HELM_ROOT} has no charts/" >&2; exit 1; }

mkdir -p "${OUT}"

helm_tpl() {
  local name="$1" ns="$2" chart="$3"
  shift 3
  echo "Rendering ${name}"
  helm template "$name" "$chart" -n "$ns" "$@" > "${OUT}/${name}.yaml"
}

cd "${HELM_ROOT}"
for c in cert-manager rhcl leaderworkerset openshift-ai observability-operators platform-addons; do
  (cd "${CHARTS}/${c}" && helm dependency update >/dev/null)
done
if [[ ! -f "${CHARTS}/platform-addons/charts/install-operators-0.1.0.tgz" ]]; then
  mkdir -p "${CHARTS}/platform-addons/charts"
  helm package "${CHARTS}/install-operators" -d "${CHARTS}/platform-addons/charts" >/dev/null
fi

helm_tpl cert-manager cert-manager-operator "${CHARTS}/cert-manager" \
  -f "${CLUSTER}/cluster.yaml" -f "${CLUSTER}/platform/values/cert-manager/values.yaml"
helm_tpl observability-operators openshift-operators "${CHARTS}/observability-operators" \
  -f "${CLUSTER}/cluster.yaml" -f "${CLUSTER}/platform/values/observability-operators/values.yaml"
helm_tpl platform-addons rhoai-model-registries "${CHARTS}/platform-addons" \
  -f "${CLUSTER}/cluster.yaml" -f "${CLUSTER}/platform/values/platform-addons/values.yaml" \
  --set modelRegistry.createCR=true
helm_tpl leaderworkerset openshift-lws-operator "${CHARTS}/leaderworkerset" \
  -f "${CLUSTER}/cluster.yaml" -f "${CLUSTER}/platform/values/leaderworkerset/values.yaml"
helm_tpl rhcl kuadrant-system "${CHARTS}/rhcl" \
  -f "${CLUSTER}/cluster.yaml" -f "${CLUSTER}/platform/values/rhcl/values.yaml"
helm_tpl gateway-api openshift-ingress "${CHARTS}/gateway-api" \
  -f "${CLUSTER}/cluster.yaml" -f "${CLUSTER}/platform/values/gateway-api/values.yaml"
helm_tpl maas-postgres redhat-ods-applications "${CHARTS}/maas-postgres" \
  -f "${CLUSTER}/cluster.yaml" -f "${CLUSTER}/platform/values/maas-postgres/values.yaml"
helm_tpl openshift-ai redhat-ods-operator "${CHARTS}/openshift-ai" \
  -f "${CLUSTER}/cluster.yaml" -f "${CLUSTER}/platform/values/openshift-ai/values.yaml"
helm_tpl llmisvc-granite ai-models "${CHARTS}/llmisvc" \
  -f "${CLUSTER}/cluster.yaml" -f "${CLUSTER}/values/llmisvc/granite-3.1-2b-instruct.yaml"
helm_tpl maas-subscriptions models-as-a-service "${CHARTS}/maas-subscriptions" \
  -f "${CLUSTER}/cluster.yaml" -f "${CLUSTER}/values/maas-subscriptions/values.yaml"

python3 "${GITOPS_ROOT}/hack/split-rendered.py" "${OUT}" "${GITOPS_ROOT}/components"
echo "Updated ${GITOPS_ROOT}/components/*/base from Helm. Review git diff."
