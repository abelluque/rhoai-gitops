#!/usr/bin/env bash
# Optional one-shot importer. Committed Kustomize manifests in this repository
# are the source of truth; operators do not need Helm or a local charts tree
# to deploy.
#
# When a charts checkout is available (sibling directory named rhoai-helm, or
# HELM_ROOT), this script re-renders overlays. It does not commit.
#
# Usage:
#   CLUSTER_NAME=opentlc ./hack/import-from-helm.sh
#   CLUSTER_NAME=ocpai-prd-mtz ./hack/import-from-helm.sh
#   HELM_ROOT=/path/to/rhoai-helm CLUSTER_NAME=ocpai-prd-mtz ./hack/import-from-helm.sh
set -euo pipefail

GITOPS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLUSTER_NAME="${CLUSTER_NAME:-opentlc}"

if [[ -z "${HELM_ROOT:-}" ]]; then
  if [[ -d "${GITOPS_ROOT}/../rhoai-helm/charts" ]]; then
    HELM_ROOT="$(cd "${GITOPS_ROOT}/../rhoai-helm" && pwd)"
  else
    echo "Helm is not required to operate this GitOps repository." >&2
    echo "To re-render overlays, set HELM_ROOT to a rhoai-helm charts checkout." >&2
    exit 1
  fi
fi

CLUSTER="${CLUSTER:-${HELM_ROOT}/clusters/${CLUSTER_NAME}}"
CHARTS="${CHARTS:-${HELM_ROOT}/charts}"
OUT="${GITOPS_ROOT}/.rendered/${CLUSTER_NAME}"

command -v helm >/dev/null || { echo "helm is required only for this optional importer" >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }
[[ -d "${CHARTS}" ]] || { echo "HELM_ROOT has no charts/: ${HELM_ROOT}" >&2; exit 1; }
[[ -f "${CLUSTER}/cluster.yaml" ]] || { echo "Missing ${CLUSTER}/cluster.yaml" >&2; exit 1; }

if [[ "${CLUSTER_NAME}" == "opentlc" ]]; then
  WRITE_MODE="base"
else
  WRITE_MODE="overlay"
fi

mkdir -p "${OUT}"
rm -f "${OUT}"/*.yaml

helm_tpl() {
  local name="$1" ns="$2" chart="$3"
  shift 3
  echo "Rendering ${name}"
  helm template "$name" "$chart" -n "$ns" "$@" > "${OUT}/${name}.yaml"
}

cd "${HELM_ROOT}"
DEPS=(cert-manager rhcl leaderworkerset openshift-ai observability-operators platform-addons)
if [[ "${CLUSTER_NAME}" == "ocpai-prd-mtz" ]]; then
  DEPS+=(nvidia-gpu-enablement)
fi
for c in "${DEPS[@]}"; do
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

if [[ "${CLUSTER_NAME}" == "ocpai-prd-mtz" ]]; then
  helm_tpl nvidia-gpu-enablement openshift-nfd "${CHARTS}/nvidia-gpu-enablement" \
    -f "${CLUSTER}/cluster.yaml" -f "${CLUSTER}/platform/values/nvidia-gpu-enablement/values.yaml"
  helm_tpl llmisvc-granite-8b ai-models "${CHARTS}/llmisvc" \
    -f "${CLUSTER}/cluster.yaml" -f "${CLUSTER}/values/llmisvc/granite-3.0-8b-instruct.yaml"
  helm_tpl llmisvc-qwen25-coder-32b ai-models "${CHARTS}/llmisvc" \
    -f "${CLUSTER}/cluster.yaml" -f "${CLUSTER}/values/llmisvc/qwen2.5-coder-32b.yaml"
  helm_tpl llmisvc-deepseek-coder-33b ai-models "${CHARTS}/llmisvc" \
    -f "${CLUSTER}/cluster.yaml" -f "${CLUSTER}/values/llmisvc/deepseek-coder-33b.yaml"
elif [[ "${CLUSTER_NAME}" == "opentlc" ]]; then
  helm_tpl llmisvc-granite ai-models "${CHARTS}/llmisvc" \
    -f "${CLUSTER}/cluster.yaml" -f "${CLUSTER}/values/llmisvc/granite-3.1-2b-instruct.yaml"
fi

helm_tpl maas-subscriptions models-as-a-service "${CHARTS}/maas-subscriptions" \
  -f "${CLUSTER}/cluster.yaml" -f "${CLUSTER}/values/maas-subscriptions/values.yaml"

python3 "${GITOPS_ROOT}/hack/split-rendered.py" "${OUT}" "${GITOPS_ROOT}/components" \
  --overlay "${CLUSTER_NAME}" --mode "${WRITE_MODE}"
echo "Updated components for overlay ${CLUSTER_NAME} (mode=${WRITE_MODE}). Review git diff before committing."
