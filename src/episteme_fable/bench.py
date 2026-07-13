"""Benchmark: run the engine over gold docs and score against gold labels.

Metrics (per doc + micro-average):
- claim precision / recall / F1 — greedy one-to-one matching on symmetric
  content-token overlap (prefix-tolerant), threshold MATCH_FLOOR
- compression — predicted claims / gold claims (1.0 is perfect; the old
  engine ran ~4x)
- funnel — proposals, accepted, rejections by stage
- thesis agreement — same matching against gold theses, lower floor

Optional --judge: an LLM adjudicates lexically-unmatched gold claims
against leftover predictions, since two correct rewrites of the same
proposition need not share surface tokens. Judge verdicts only ever ADD
matches; the deterministic floor is the pessimistic baseline.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .pipeline import analyze
from .providers import ClaudeCLIProvider, extract_json
from .store import load_jsonl, write_json
from .validate import content_tokens, _tok_match

MATCH_FLOOR = 0.5
THESIS_FLOOR = 0.35


def _overlap(a: str, b: str) -> float:
    ta, tb = content_tokens(a), content_tokens(b)
    if not ta or not tb:
        return 0.0
    sa, sb = set(ta), set(tb)
    hit_a = sum(1 for t in sa if _tok_match(t, sb))
    hit_b = sum(1 for t in sb if _tok_match(t, sa))
    return (hit_a + hit_b) / (len(sa) + len(sb))


def _greedy_match(gold: list[str], pred: list[str],
                  floor: float) -> list[tuple[int, int, float]]:
    scored = []
    for i, g in enumerate(gold):
        for j, p in enumerate(pred):
            s = _overlap(g, p)
            if s >= floor:
                scored.append((s, i, j))
    scored.sort(reverse=True)
    used_g, used_p, pairs = set(), set(), []
    for s, i, j in scored:
        if i in used_g or j in used_p:
            continue
        used_g.add(i)
        used_p.add(j)
        pairs.append((i, j, s))
    return pairs


def _judge_pairs(judge, gold_left: list[tuple[int, str]],
                 pred_left: list[tuple[int, str]], model: str
                 ) -> list[tuple[int, int]]:
    """Ask the judge which unmatched gold claims are expressed by which
    leftover predictions. Conservative: only exact index pairs accepted."""
    if not gold_left or not pred_left:
        return []
    gold_block = "\n".join(f"G{i}: {t}" for i, t in gold_left)
    pred_block = "\n".join(f"P{j}: {t}" for j, t in pred_left)
    prompt = f"""Two lists of claims extracted from the same document by different
annotators. For each G-claim, decide whether some P-claim expresses the SAME
proposition (same subject, same predication, same modality — wording may
differ). Be strict: partial overlap or related-topic is NOT a match.

{gold_block}

{pred_block}

Reply with a JSON array of matches only, e.g. [["G0","P3"],["G2","P1"]].
Claims with no match are simply omitted. No commentary."""
    try:
        reply = judge.complete(prompt, model=model)
    except Exception:
        return []
    data, err = extract_json(reply)
    if err or not isinstance(data, list):
        return []
    out = []
    gset = {f"G{i}" for i, _ in gold_left}
    pset = {f"P{j}" for j, _ in pred_left}
    for item in data:
        if (isinstance(item, list) and len(item) == 2
                and item[0] in gset and item[1] in pset):
            out.append((int(item[0][1:]), int(item[1][1:])))
    return out


def run_bench(gold_dir: Path, out_dir: Path, model: str,
              assemble_model: str, use_judge: bool, judge_model: str,
              reuse: bool) -> int:
    docs_dir = gold_dir / "docs"
    labels_dir = gold_dir / "labels"
    names = sorted(p.stem for p in docs_dir.glob("*.md")
                   if (labels_dir / f"{p.stem}.json").exists())
    if not names:
        print("no gold docs with labels found")
        return 2

    run_dir = out_dir / time.strftime("%Y%m%d-%H%M%S")
    cache_dir = out_dir / "cache"
    provider = ClaudeCLIProvider(model=model)
    judge = ClaudeCLIProvider(model=judge_model) if use_judge else None

    rows = []
    totals = {"gold": 0, "pred": 0, "matched": 0,
              "gold_theses": 0, "pred_theses": 0, "matched_theses": 0,
              "proposals": 0, "rejected": 0}
    reject_stages: dict[str, int] = {}

    for name in names:
        gold = json.loads((labels_dir / f"{name}.json").read_text())
        gold_claims = [c["text"] for c in gold["claims"]]
        gold_theses = [t["text"] for t in gold["theses"]]

        cache = cache_dir / name
        if reuse and (cache / "claims.jsonl").exists():
            pred_claims = [r["text"] for r in load_jsonl(cache / "claims.jsonl")]
            pred_theses = [r["text"] for r in load_jsonl(cache / "theses.jsonl")]
            stats = json.loads((cache / "stats.json").read_text())
        else:
            raw = (docs_dir / f"{name}.md").read_text()
            print(f"  analyzing {name} ...", flush=True)
            art = analyze(raw, doc_id=name, title=name.replace("-", " "),
                          provider=provider, model=model,
                          assemble_model=assemble_model)
            pred_claims = [c.text for c in art.claims]
            pred_theses = [t.text for t in art.theses]
            stats = art.stats
            from .store import write_jsonl
            write_jsonl(cache / "claims.jsonl",
                        (c.to_dict() for c in art.claims))
            write_jsonl(cache / "theses.jsonl",
                        (t.to_dict() for t in art.theses))
            write_jsonl(cache / "rejections.jsonl",
                        (r.to_dict() for r in art.rejections))
            write_json(cache / "stats.json", stats)

        pairs = _greedy_match(gold_claims, pred_claims, MATCH_FLOOR)
        judged = 0
        if judge is not None:
            mg = {i for i, _, _ in pairs}
            mp = {j for _, j, _ in pairs}
            gold_left = [(i, t) for i, t in enumerate(gold_claims) if i not in mg]
            pred_left = [(j, t) for j, t in enumerate(pred_claims) if j not in mp]
            extra = _judge_pairs(judge, gold_left, pred_left, judge_model)
            seen_g = {i for i, _, _ in pairs}
            seen_p = {j for _, j, _ in pairs}
            for gi, pj in extra:
                if gi in seen_g or pj in seen_p:
                    continue
                pairs.append((gi, pj, -1.0))  # -1 marks judge match
                seen_g.add(gi)
                seen_p.add(pj)
                judged += 1

        t_pairs = _greedy_match(gold_theses, pred_theses, THESIS_FLOOR)

        n_g, n_p, n_m = len(gold_claims), len(pred_claims), len(pairs)
        prec = n_m / n_p if n_p else 0.0
        rec = n_m / n_g if n_g else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        rows.append({
            "doc": name, "gold": n_g, "pred": n_p, "matched": n_m,
            "judge_matched": judged,
            "precision": round(prec, 3), "recall": round(rec, 3),
            "f1": round(f1, 3),
            "compression": round(n_p / n_g, 2) if n_g else None,
            "gold_theses": len(gold_theses), "pred_theses": len(pred_theses),
            "matched_theses": len(t_pairs),
            "proposals": stats.get("proposals"),
            "rejected": stats.get("rejected"),
            "rejected_by_stage": stats.get("rejected_by_stage", {}),
            "unmatched_gold": [gold_claims[i] for i in range(n_g)
                               if i not in {i for i, _, _ in pairs}],
            "unmatched_pred": [pred_claims[j] for j in range(n_p)
                               if j not in {j for _, j, _ in pairs}],
            "gold_theses_texts": gold_theses,
            "pred_theses_texts": pred_theses,
        })
        totals["gold"] += n_g
        totals["pred"] += n_p
        totals["matched"] += n_m
        totals["gold_theses"] += len(gold_theses)
        totals["pred_theses"] += len(pred_theses)
        totals["matched_theses"] += len(t_pairs)
        totals["proposals"] += stats.get("proposals", 0)
        totals["rejected"] += stats.get("rejected", 0)
        for k, v in stats.get("rejected_by_stage", {}).items():
            reject_stages[k] = reject_stages.get(k, 0) + v
        print(f"  {name}: P {prec:.2f} R {rec:.2f} F1 {f1:.2f} "
              f"({n_p} pred / {n_g} gold, {judged} judge-matched)", flush=True)

    micro_p = totals["matched"] / totals["pred"] if totals["pred"] else 0.0
    micro_r = totals["matched"] / totals["gold"] if totals["gold"] else 0.0
    micro_f = (2 * micro_p * micro_r / (micro_p + micro_r)
               if micro_p + micro_r else 0.0)
    summary = {
        "docs": len(names), "model": model, "assemble_model": assemble_model,
        "judge": use_judge,
        "micro_precision": round(micro_p, 3),
        "micro_recall": round(micro_r, 3),
        "micro_f1": round(micro_f, 3),
        "compression": round(totals["pred"] / totals["gold"], 2),
        "thesis_recall": round(totals["matched_theses"] / totals["gold_theses"], 3)
        if totals["gold_theses"] else None,
        "proposals": totals["proposals"], "rejected": totals["rejected"],
        "rejected_by_stage": reject_stages,
    }
    write_json(run_dir / "results.json", {"summary": summary, "docs": rows})
    (run_dir / "report.md").write_text(_render(summary, rows), encoding="utf-8")
    print(f"\nmicro: P {micro_p:.3f} R {micro_r:.3f} F1 {micro_f:.3f} "
          f"compression {summary['compression']}")
    print(f"-> {run_dir}/report.md")
    return 0


def _render(summary: dict, rows: list[dict]) -> str:
    L = [f"# Bench run — {summary['docs']} docs, model {summary['model']}", ""]
    L.append(f"**micro P {summary['micro_precision']} · "
             f"R {summary['micro_recall']} · F1 {summary['micro_f1']} · "
             f"compression {summary['compression']} · "
             f"thesis recall {summary['thesis_recall']}**")
    L.append("")
    L.append(f"funnel: {summary['proposals']} proposals, "
             f"{summary['rejected']} rejected {summary['rejected_by_stage']}")
    L.append("")
    L.append("| doc | gold | pred | match (judge) | P | R | F1 | compr | theses |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        L.append(f"| {r['doc']} | {r['gold']} | {r['pred']} | "
                 f"{r['matched']} ({r['judge_matched']}) | {r['precision']} | "
                 f"{r['recall']} | {r['f1']} | {r['compression']} | "
                 f"{r['matched_theses']}/{r['gold_theses']} |")
    L.append("")
    for r in rows:
        if not r["unmatched_gold"] and not r["unmatched_pred"]:
            continue
        L.append(f"## {r['doc']}")
        if r["unmatched_gold"]:
            L.append("**Missed gold claims:**")
            for t in r["unmatched_gold"]:
                L.append(f"- {t}")
        if r["unmatched_pred"]:
            L.append("**Unmatched predictions:**")
            for t in r["unmatched_pred"]:
                L.append(f"- {t}")
        L.append("**Theses gold vs predicted:**")
        for t in r["gold_theses_texts"]:
            L.append(f"- G: {t}")
        for t in r["pred_theses_texts"]:
            L.append(f"- P: {t}")
        L.append("")
    return "\n".join(L)
