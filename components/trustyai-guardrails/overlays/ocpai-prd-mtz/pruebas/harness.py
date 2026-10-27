import json
import os
import ssl
import sys
import time
import urllib.request
from collections import defaultdict

URL = os.environ.get("NEMO_URL", "https://nemo-icbc.rhoai-trustyai-guardrails.svc").rstrip("/") + "/v1/guardrail/checks"
TOKEN_FILE = os.environ.get("TOKEN_FILE", "/var/run/secrets/kubernetes.io/serviceaccount/token")
DATASET = os.environ.get("DATASET", "/pruebas/dataset.jsonl")
CA_FILE = os.environ.get("CA_FILE", "/var/run/secrets/kubernetes.io/serviceaccount/service-ca.crt")
TIMEOUT = float(os.environ.get("TIMEOUT", "30"))
FORCE_CONFIG = os.environ.get("FORCE_CONFIG", "")


def context():
    if os.path.exists(CA_FILE):
        return ssl.create_default_context(cafile=CA_FILE)
    return ssl.create_default_context()


def token():
    if os.environ.get("TOKEN"):
        return os.environ["TOKEN"]
    with open(TOKEN_FILE) as f:
        return f.read().strip()


def check(ctx, tok, case, config):
    body = {"model": "p", "messages": [{"role": case["role"], "content": case["texto"]}],
            "guardrails": {"config_id": config}}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {tok}"})
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as resp:
            status = json.loads(resp.read()).get("status")
        error = None
    except Exception as exc:
        status, error = None, type(exc).__name__
    return status, round((time.monotonic() - start) * 1000), error


def pct(values, p):
    if not values:
        return None
    values = sorted(values)
    return values[min(len(values) - 1, int(round(p / 100 * (len(values) - 1))))]


def ratio(a, b):
    return round(a / b, 3) if b else None


def main():
    cases = [json.loads(line) for line in open(DATASET) if line.strip()]
    ctx, tok = context(), token()
    results = []
    for case in cases:
        for config in ([FORCE_CONFIG] if FORCE_CONFIG else case["configs"]):
            status, ms, error = check(ctx, tok, case, config)
            got = "BLOCK" if status == "blocked" else "ALLOW" if status == "success" else "ERROR"
            verdict = "PASS" if got == case["esperado"] else "ERROR" if got == "ERROR" else "FAIL"
            results.append({**case, "config": config, "obtenido": got, "resultado": verdict, "latencia_ms": ms, "error": error})
            print(json.dumps({"caso": case["id"], "config": config, "tipo": case["tipo"], "esperado": case["esperado"],
                              "obtenido": got, "resultado": verdict, "latencia_ms": ms, "error": error}, ensure_ascii=False))

    groups = defaultdict(list)
    for r in results:
        groups[(r["dominio"], r["config"])].append(r)
    summary = []
    for (dominio, config), rs in sorted(groups.items()):
        tp = sum(r["esperado"] == "BLOCK" and r["obtenido"] == "BLOCK" for r in rs)
        tn = sum(r["esperado"] == "ALLOW" and r["obtenido"] == "ALLOW" for r in rs)
        fp = sum(r["esperado"] == "ALLOW" and r["obtenido"] == "BLOCK" for r in rs)
        fn = sum(r["esperado"] == "BLOCK" and r["obtenido"] == "ALLOW" for r in rs)
        err = sum(r["obtenido"] == "ERROR" for r in rs)
        precision, recall = ratio(tp, tp + fp), ratio(tp, tp + fn)
        f1 = round(2 * precision * recall / (precision + recall), 3) if precision and recall else None
        lat = [r["latencia_ms"] for r in rs if r["obtenido"] != "ERROR"]
        row = {"dominio": dominio, "config": config, "casos": len(rs), "tp": tp, "tn": tn, "fp": fp, "fn": fn,
               "errores": err, "precision": precision, "recall": recall, "f1": f1,
               "fp_rate": ratio(fp, fp + tn), "p50_ms": pct(lat, 50), "p95_ms": pct(lat, 95), "p99_ms": pct(lat, 99)}
        summary.append(row)
    print()
    print(f"{'dominio':18} {'config':9} {'casos':>5} {'TP':>3} {'TN':>3} {'FP':>3} {'FN':>3} {'ERR':>3} "
          f"{'prec':>6} {'recall':>6} {'F1':>6} {'p50':>6} {'p95':>6} {'p99':>6}")
    for s in summary:
        print(f"{s['dominio']:18} {s['config']:9} {s['casos']:>5} {s['tp']:>3} {s['tn']:>3} {s['fp']:>3} {s['fn']:>3} "
              f"{s['errores']:>3} {str(s['precision']):>6} {str(s['recall']):>6} {str(s['f1']):>6} "
              f"{str(s['p50_ms']):>6} {str(s['p95_ms']):>6} {str(s['p99_ms']):>6}")
    print()
    print(json.dumps({"event": "guardrails_harness_summary", "casos": len(cases), "ejecuciones": len(results),
                      "pass": sum(r["resultado"] == "PASS" for r in results),
                      "fail": sum(r["resultado"] == "FAIL" for r in results),
                      "error": sum(r["resultado"] == "ERROR" for r in results), "metricas": summary},
                     ensure_ascii=False))


if __name__ == "__main__":
    sys.exit(main())
