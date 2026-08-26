#!/usr/bin/env bash
# Cluster-admin diagnostic dump of OpenShift GitOps Applications.
# Prints sync and health status, operation messages, truncated conditions, and
# failed resources. Does not print Secret data, tokens, or credentials.
#
# Usage:
#   ./hack/argocd-sync-report.sh
#   ./hack/argocd-sync-report.sh /tmp/argocd-sync-report.txt
set -euo pipefail

NS="${ARGOCD_NS:-openshift-gitops}"
EVENTS_TAIL="${EVENTS_TAIL:-40}"
COND_MSG_MAX="${COND_MSG_MAX:-400}"
ERR_MSG_MAX="${ERR_MSG_MAX:-800}"

if [[ $# -gt 1 ]]; then
  echo "Usage: $0 [output-file]" >&2
  exit 2
fi
OUT_FILE="${1:-}"

command -v oc >/dev/null || { echo "oc is required" >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }
oc whoami >/dev/null || { echo "Not logged in. Run oc login first." >&2; exit 1; }

emit() {
  if [[ -n "${OUT_FILE}" ]]; then
    tee "${OUT_FILE}"
  else
    cat
  fi
}

print_app_details() {
  COND_MSG_MAX="${COND_MSG_MAX}" ERR_MSG_MAX="${ERR_MSG_MAX}" python3 -c '
import json, os, sys

cond_max = int(os.environ.get("COND_MSG_MAX", "400"))
err_max = int(os.environ.get("ERR_MSG_MAX", "800"))
fail_status = {"failed", "syncfailed", "prunefailed"}
fail_health = {"degraded", "missing"}


def trunc(text, limit):
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def is_fail_status(value):
    return str(value or "").lower() in fail_status


def is_fail_health(value):
    return str(value or "").lower() in fail_health


raw = sys.stdin.read()
if not raw.strip():
    print("(unable to read Application list JSON)")
    sys.exit(0)
try:
    doc = json.loads(raw)
except json.JSONDecodeError:
    print("(unable to parse Application list JSON)")
    sys.exit(0)

items = doc.get("items") or []
if not items:
    print("(no Applications found)")
    sys.exit(0)

items.sort(key=lambda a: (a.get("metadata") or {}).get("name") or "")

for app in items:
    meta = app.get("metadata") or {}
    st = app.get("status") or {}
    name = meta.get("name") or "?"
    sync = (st.get("sync") or {}).get("status") or "Unknown"
    health = st.get("health") or {}
    health_status = health.get("status") or "Unknown"
    health_msg = trunc(health.get("message"), err_max)
    op = st.get("operationState") or {}
    op_phase = op.get("phase") or ""
    op_msg = trunc(op.get("message"), err_max)
    op_started = op.get("startedAt") or ""
    op_finished = op.get("finishedAt") or ""

    print("-------- %s --------" % name)
    print("sync: %s" % sync)
    line = "health: %s" % health_status
    if health_msg:
        line += " (%s)" % health_msg
    print(line)
    if op_phase or op_msg:
        line = "operation: %s" % (op_phase or "n/a")
        if op_msg:
            line += " | %s" % op_msg
        print(line)
        if op_started or op_finished:
            print("operation_times: started=%s finished=%s" % (op_started or "n/a", op_finished or "n/a"))
    else:
        print("operation: (none)")

    conditions = st.get("conditions") or []
    if conditions:
        print("conditions:")
        for cond in conditions:
            ctype = cond.get("type") or "?"
            cstatus = cond.get("status") or ""
            cmsg = trunc(cond.get("message"), cond_max)
            when = cond.get("lastTransitionTime") or ""
            extra = [x for x in (cstatus, when) if x]
            prefix = "  - %s" % ctype
            if extra:
                prefix += " [%s]" % ", ".join(extra)
            print(prefix + (": %s" % cmsg if cmsg else ""))
    else:
        print("conditions: (none)")

    failed = []
    seen = set()

    def add_failed(res, source):
        if not isinstance(res, dict):
            return
        health_obj = res.get("health") if isinstance(res.get("health"), dict) else {}
        group = res.get("group") or ""
        kind = res.get("kind") or ""
        ns = res.get("namespace") or ""
        rname = res.get("name") or ""
        rstatus = res.get("status") or ""
        rhealth = health_obj.get("status") or ""
        msg = trunc(res.get("message"), err_max)
        ident = (group, kind, ns, rname, rstatus, rhealth, msg, source)
        if ident in seen:
            return
        seen.add(ident)
        failed.append(
            {
                "group": group,
                "kind": kind,
                "namespace": ns,
                "name": rname,
                "status": rstatus,
                "health": rhealth,
                "message": msg,
                "source": source,
            }
        )

    for res in ((op.get("syncResult") or {}).get("resources")) or []:
        if is_fail_status(res.get("status")):
            add_failed(res, "syncResult")

    for res in st.get("resources") or []:
        rhealth = ""
        if isinstance(res.get("health"), dict):
            rhealth = (res.get("health") or {}).get("status") or ""
        if is_fail_status(res.get("status")) or is_fail_health(rhealth):
            add_failed(res, "resources")

    if failed:
        print("failed_resources:")
        for item in failed:
            print(
                "  - group=%s kind=%s ns=%s name=%s"
                % (
                    item["group"] or "core",
                    item["kind"] or "?",
                    item["namespace"] or "-",
                    item["name"] or "?",
                )
            )
            bits = []
            if item["status"]:
                bits.append("status=%s" % item["status"])
            if item["health"]:
                bits.append("health=%s" % item["health"])
            bits.append("source=%s" % item["source"])
            print("    %s" % " ".join(bits))
            if item["message"]:
                print("    error: %s" % item["message"])
    else:
        print("failed_resources: (none)")
    print()
'
}

{
  echo "=== OpenShift GitOps Application report ==="
  echo "generated_at_utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "user: $(oc whoami 2>/dev/null || echo unknown)"
  echo "server: $(oc whoami --show-server 2>/dev/null || echo unknown)"
  echo "clusterversion: $(oc get clusterversion version -o jsonpath='{.status.desired.version}' 2>/dev/null || echo unknown)"
  echo "namespace: ${NS}"
  echo

  echo "=== oc get applications.argoproj.io -n ${NS} ==="
  oc get applications.argoproj.io -n "${NS}" 2>&1 || true
  echo

  echo "=== Application details (no secrets) ==="
  if oc get applications.argoproj.io -n "${NS}" -o json >/dev/null 2>&1; then
    oc get applications.argoproj.io -n "${NS}" -o json | print_app_details
  else
    echo "(unable to list Applications as JSON)"
  fi
  echo

  echo "=== oc get events -n ${NS} (last ${EVENTS_TAIL}) ==="
  if ! oc get events -n "${NS}" --sort-by=.lastTimestamp 2>/dev/null | tail -n "${EVENTS_TAIL}"; then
    oc get events -n "${NS}" 2>/dev/null | tail -n "${EVENTS_TAIL}" || echo "(unable to list events)"
  fi
  echo
  echo "=== end of report ==="
} | emit
