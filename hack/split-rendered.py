#!/usr/bin/env python3
"""Split helm template output into Kustomize component bases. Convert Helm hooks to Argo CD."""
import re
import sys
from pathlib import Path

def split_docs(text):
    parts = re.split(r"(?m)^---\s*$", text)
    return [p.strip() for p in parts if p.strip() and re.search(r"(?m)^kind:", p)]

def header_map(doc):
    kind = ns = name = None
    in_meta = False
    for line in doc.splitlines():
        if re.match(r"^(spec|data|status|stringData):", line):
            break
        m = re.match(r"^kind:\s*(.+)$", line)
        if m:
            kind = m.group(1).strip()
            continue
        if re.match(r"^metadata:\s*$", line):
            in_meta = True
            continue
        if in_meta:
            m = re.match(r"^  name:\s*(.+)$", line)
            if m and name is None:
                name = m.group(1).strip().strip('"').strip("'")
                continue
            m = re.match(r"^  namespace:\s*(.+)$", line)
            if m and ns is None:
                ns = m.group(1).strip().strip('"').strip("'")
                continue
            if re.match(r"^\S", line) and not line.startswith(" "):
                break
    return kind or "unknown", ns or "", name or "unnamed"

def clean(doc):
    doc = re.sub(r"(?m)^\s+helm\.sh/chart:.*\n", "", doc)
    doc = re.sub(r"(?m)^\s+app\.kubernetes\.io/managed-by: Helm\n", "", doc)
    doc = re.sub(r"(?m)^\s+meta\.helm\.sh/.*\n", "", doc)
    hook = re.search(r"helm\.sh/hook:\s*(.+)", doc)
    weight = re.search(r"helm\.sh/hook-weight:\s*[\"']?([^\"'\n]+)", doc)
    delete = re.search(r"helm\.sh/hook-delete-policy:\s*(.+)", doc)
    doc = re.sub(r"(?m)^\s+helm\.sh/hook:.*\n", "", doc)
    doc = re.sub(r"(?m)^\s+helm\.sh/hook-weight:.*\n", "", doc)
    doc = re.sub(r"(?m)^\s+helm\.sh/hook-delete-policy:.*\n", "", doc)
    if hook and ("post-install" in hook.group(1) or "post-upgrade" in hook.group(1)):
        extra = ["    argocd.argoproj.io/hook: PostSync"]
        if delete and "before-hook-creation" in delete.group(1):
            extra.append("    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation")
        if weight:
            extra.append(f'    argocd.argoproj.io/sync-wave: "{weight.group(1).strip()}"')
        extra_txt = "\n".join(extra) + "\n"
        if re.search(r"(?m)^  annotations:\n", doc):
            doc = re.sub(r"(?m)^  annotations:\n", "  annotations:\n" + extra_txt, doc, count=1)
        else:
            doc = re.sub(r"(?m)^metadata:\n", "metadata:\n  annotations:\n" + extra_txt, doc, count=1)
    return doc

def fname(kind, ns, name):
    safe = re.sub(r"[^a-z0-9.-]+", "-", name.lower())[:80]
    kind = re.sub(r"[^a-z0-9]+", "-", kind.lower())
    if ns:
        return f"{kind}-{ns}-{safe}.yaml"
    return f"{kind}-{safe}.yaml"

def main():
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    for rendered in sorted(src.glob("*.yaml")):
        comp = rendered.stem
        outdir = dst / comp / "base"
        outdir.mkdir(parents=True, exist_ok=True)
        for p in outdir.glob("*.yaml"):
            p.unlink()
        seen = set()
        files = []
        for raw in split_docs(rendered.read_text()):
            kind, ns, name = header_map(raw)
            key = (kind, ns, name)
            if key in seen:
                continue
            seen.add(key)
            fn = fname(kind, ns, name)
            path = outdir / fn
            i = 2
            while path.exists():
                path = outdir / fn.replace(".yaml", f"-{i}.yaml")
                i += 1
            path.write_text(clean(raw).rstrip() + "\n")
            files.append(path.name)
        kust = "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources:\n"
        kust += "".join(f"- {f}\n" for f in sorted(files))
        (outdir / "kustomization.yaml").write_text(kust)
        overlay = dst / comp / "overlays" / "opentlc"
        overlay.mkdir(parents=True, exist_ok=True)
        (overlay / "kustomization.yaml").write_text(
            "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources:\n  - ../../base\n"
        )
        print(f"{comp:24} {len(files):3} resources")

if __name__ == "__main__":
    main()
