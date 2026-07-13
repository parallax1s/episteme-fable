"""CLI: epf analyze | epf bench | epf report."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from . import ENGINE_VERSION
from .pipeline import analyze
from .providers import ASSEMBLE_MODEL, DEFAULT_MODEL, make_provider
from .report import render
from .store import write_json, write_jsonl


def _cmd_analyze(args: argparse.Namespace) -> int:
    src = Path(args.file)
    if not src.exists():
        print(f"no such file: {src}", file=sys.stderr)
        return 2
    raw = src.read_text(encoding="utf-8")
    doc_id = args.doc_id or src.stem
    title = args.title or src.stem.replace("-", " ").replace("_", " ")

    provider = make_provider(args.model)
    t0 = time.time()

    def progress(msg: str) -> None:
        print(f"  … {msg}", file=sys.stderr)

    art = analyze(raw, doc_id=doc_id, title=title, provider=provider,
                  model=args.model, assemble_model=args.assemble_model,
                  do_assemble=not args.no_assemble, on_progress=progress)

    out = Path(args.out) / doc_id
    write_jsonl(out / "claims.jsonl", (c.to_dict() for c in art.claims))
    write_jsonl(out / "points.jsonl", (p.to_dict() for p in art.points))
    write_jsonl(out / "theses.jsonl", (t.to_dict() for t in art.theses))
    write_jsonl(out / "rejections.jsonl", (r.to_dict() for r in art.rejections))
    write_json(out / "document.json", {
        "doc_id": doc_id, "title": title,
        "nodes": [art.tree.nodes[i].to_dict() for i in art.tree.order],
        "text": art.tree.text,
    })
    write_json(out / "stats.json", art.stats)
    (out / "report.md").write_text(render(art), encoding="utf-8")

    s = art.stats
    print(f"{doc_id}: {s['accepted']} claims, {s['points']} points, "
          f"{s['theses']} theses ({s['rejected']} rejected) "
          f"in {time.time() - t0:.0f}s -> {out}")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    p = Path(args.dir) / "report.md"
    if not p.exists():
        print(f"no report at {p}", file=sys.stderr)
        return 2
    print(p.read_text(encoding="utf-8"))
    return 0


def _cmd_bench(args: argparse.Namespace) -> int:
    from .bench import run_bench
    return run_bench(gold_dir=Path(args.gold), out_dir=Path(args.out),
                     model=args.model, assemble_model=args.assemble_model,
                     use_judge=args.judge, judge_model=args.judge_model,
                     reuse=args.reuse)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="epf",
                                 description="Episteme (Fable) claim engine")
    ap.add_argument("--version", action="version", version=ENGINE_VERSION)
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("analyze", help="extract the pyramid from a document")
    a.add_argument("file")
    a.add_argument("--doc-id")
    a.add_argument("--title")
    a.add_argument("--model", default=DEFAULT_MODEL)
    a.add_argument("--assemble-model", default=ASSEMBLE_MODEL)
    a.add_argument("--out", default="out")
    a.add_argument("--no-assemble", action="store_true")
    a.set_defaults(fn=_cmd_analyze)

    r = sub.add_parser("report", help="print a saved report")
    r.add_argument("dir")
    r.set_defaults(fn=_cmd_report)

    b = sub.add_parser("bench", help="run the gold benchmark")
    b.add_argument("--gold", default="gold")
    b.add_argument("--out", default="bench/runs")
    b.add_argument("--model", default=DEFAULT_MODEL)
    b.add_argument("--assemble-model", default=ASSEMBLE_MODEL)
    b.add_argument("--judge", action="store_true",
                   help="LLM-judge lexically-unmatched pairs (better recall measurement)")
    b.add_argument("--judge-model", default=ASSEMBLE_MODEL)
    b.add_argument("--reuse", action="store_true",
                   help="reuse cached engine outputs from a previous bench run")
    b.set_defaults(fn=_cmd_bench)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
