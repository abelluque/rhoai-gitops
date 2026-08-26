#!/usr/bin/env python3
"""Split helm template output into Kustomize component directories.

Convert Helm hooks to Argo CD PostSync hooks and strip Helm managed-by labels.

Modes:
  base     Write components/<name>/base and an overlay that points at ../../base
           (OpenTLC import layout).
  overlay  Write a self-contained kustomization under
           components/<name>/overlays/<overlay> without modifying base.
"""
import argparse
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
    if not doc.endswith("\n"):
        doc += "\n"
    doc = re.sub(r"(?m)^[ \t]+helm\.sh/chart:.*\n", "", doc)
    doc = re.sub(r"(?m)^[ \t]+app\.kubernetes\.io/managed-by: Helm[ \t]*\n", "", doc)
    doc = re.sub(r"(?m)^[ \t]+meta\.helm\.sh/.*\n", "", doc)
    hook = re.search(r"helm\.sh/hook:\s*(.+)", doc)
    weight = re.search(r"helm\.sh/hook-weight:\s*[\"']?([^\"'\n]+)", doc)
    delete = re.search(r"helm\.sh/hook-delete-policy:\s*(.+)", doc)
    doc = re.sub(r"(?m)^[ \t]+helm\.sh/hook:.*\n", "", doc)
    doc = re.sub(r"(?m)^[ \t]+helm\.sh/hook-weight:.*\n", "", doc)
    doc = re.sub(r"(?m)^[ \t]+helm\.sh/hook-delete-policy:.*\n", "", doc)
    if hook and ("post-install" in hook.group(1) or "post-upgrade" in hook.group(1)):
        extra = []
        if "argocd.argoproj.io/hook:" not in doc:
            extra.append("    argocd.argoproj.io/hook: PostSync")
        if delete and "before-hook-creation" in delete.group(1) and "argocd.argoproj.io/hook-delete-policy:" not in doc:
            extra.append("    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation")
        if weight and "argocd.argoproj.io/sync-wave:" not in doc:
            extra.append(f'    argocd.argoproj.io/sync-wave: "{weight.group(1).strip()}"')
        if extra:
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


def write_kustomization(outdir, files):
    kust = "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources:\n"
    kust += "".join(f"- {f}\n" for f in sorted(files))
    (outdir / "kustomization.yaml").write_text(kust)


def split_component(rendered, outdir):
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
    write_kustomization(outdir, files)
    return files


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("src")
    parser.add_argument("dst")
    parser.add_argument("--overlay", default="opentlc")
    parser.add_argument("--mode", choices=("base", "overlay"), default="base")
    args = parser.parse_args()
    src, dst = Path(args.src), Path(args.dst)
    any_files = False
    for rendered in sorted(src.glob("*.yaml")):
        comp = rendered.stem
        if not split_docs(rendered.read_text()):
            print(f"{comp:32}   0 resources (skipped empty render)")
            continue
        if args.mode == "overlay":
            outdir = dst / comp / "overlays" / args.overlay
        else:
            outdir = dst / comp / "base"
        files = split_component(rendered, outdir)
        any_files = True
        if args.mode == "base":
            overlay = dst / comp / "overlays" / args.overlay
            overlay.mkdir(parents=True, exist_ok=True)
            (overlay / "kustomization.yaml").write_text(
                "apiVersion: kustomize.config.k8s.io/v1beta1\n"
                "kind: Kustomization\n"
                "resources:\n"
                "  - ../../base\n"
            )
        print(f"{comp:32} {len(files):3} resources -> {outdir.relative_to(dst)}")
    if not any_files:
        print("No rendered documents found.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
