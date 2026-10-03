"""토큰 점검: 128 토큰 초과 비율과 [UNK] 비율 (읽기 전용, 데이터를 바꾸지 않음).

사용: 레포 루트에서  python step1_data/check_tokens.py
입력: step1_data/data/final/ 의 원문 4개 + augmented_train + obfuscated_test + obfuscated_kg_test
결과 (커밋 가능):
  step1_data/reports/token_check_summary.txt   파일별 요약 + 정규화 확인
  step1_data/reports/token_check_by_cell.csv   파일 × 모델 × 기법 × 강도별 표

토크나이저 설정은 팀 학습 레포(korean-prompt-defense)와 같게 맞춘다.
  KoELECTRA: use_fast=True (기본), mDeBERTa: use_fast=False (run_*.sh의 --use-slow-tokenizer)
토큰 수는 [CLS]/[SEP] 같은 특수 토큰을 포함한 길이 (학습 코드의 max_length=128과 같은 기준).
난독화 평가셋은 채점 기준과 같게 changed=true 행만 센다.
"""
import csv
import sys
from collections import defaultdict

from transformers import AutoTokenizer

from variants import ROOT, read_jsonl

MAX_LEN = 128
MODELS = {"koelectra": ("monologg/koelectra-base-v3-discriminator", True),
          "mdeberta": ("microsoft/mdeberta-v3-base", False)}
DATA = ROOT / "data" / "final"
FILES = ["train", "valid", "test", "kg_test", "augmented_train", "obfuscated_test", "obfuscated_kg_test"]
NORM_PROBES = ["㉵래의", "아래의", "º", "으"]       # 야민정음 특수 문자가 원래 글자로 돌아가는지
OUT_SUMMARY = ROOT / "reports" / "token_check_summary.txt"
OUT_CSV = ROOT / "reports" / "token_check_by_cell.csv"


def load_rows(name):
    rows = read_jsonl(DATA / f"{name}.jsonl")
    if name.startswith("obfuscated"):
        rows = [r for r in rows if r["changed"]]
    return rows


def measure(tok, rows):
    """행마다 (토큰 수, [UNK] 수)."""
    enc = tok([r["text"] for r in rows], add_special_tokens=True, truncation=False)["input_ids"]
    unk = tok.unk_token_id
    return [(len(ids), sum(i == unk for i in ids)) for ids in enc]


def cell_stats(items):
    """items: [(row, (n_tok, n_unk))]"""
    n = len(items)
    n_tok = sum(m[0] for _, m in items)
    over = sum(m[0] > MAX_LEN for _, m in items)
    unk_rows = sum(m[1] > 0 for _, m in items)
    by_label = {lab: [m for r, m in items if r["label"] == lab] for lab in (1, 0)}
    rate = lambda ms: round(sum(m[1] > 0 for m in ms) / len(ms), 4) if ms else ""  # noqa: E731
    return {"rows": n, "over128": over, "over128_rate": round(over / n, 4),
            "max_tokens": max(m[0] for _, m in items),
            "unk_row_rate": round(unk_rows / n, 4),
            "unk_token_rate": round(sum(m[1] for _, m in items) / n_tok, 4),
            "unk_row_rate_attack": rate(by_label[1]), "unk_row_rate_benign": rate(by_label[0])}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    data = {name: load_rows(name) for name in FILES}
    table, lines = [], []
    for key, (model_name, fast) in MODELS.items():
        tok = AutoTokenizer.from_pretrained(model_name, use_fast=fast)
        lines.append(f"===== {key} ({model_name}, use_fast={fast}) =====")
        lines.append("[정규화 확인] " + " | ".join(f"{p} → {tok.tokenize(p)}" for p in NORM_PROBES))
        lines.append(f"{'파일':<20}{'행':>8}{'128 초과':>12}{'최대 토큰':>10}{'UNK 포함 행':>14}{'UNK 토큰':>10}")
        for name in FILES:
            rows = data[name]
            pairs = list(zip(rows, measure(tok, rows)))
            s = cell_stats(pairs)
            table.append({"file": name, "model": key, "technique": "ALL", "intensity": "", **s})
            lines.append(f"{name:<20}{s['rows']:>8}{s['over128']:>6} ({s['over128_rate']:.2%}){s['max_tokens']:>10}"
                         f"{s['unk_row_rate']:>13.1%}{s['unk_token_rate']:>10.2%}")
            if name in ("augmented_train", "obfuscated_test", "obfuscated_kg_test"):
                groups = defaultdict(list)
                for r, m in pairs:
                    groups[(r.get("technique") or "original", r.get("intensity") or "")].append((r, m))
                for (t, it), items in sorted(groups.items(), key=lambda x: (x[0][0], str(x[0][1]))):
                    table.append({"file": name, "model": key, "technique": t, "intensity": it, **cell_stats(items)})
            over_rows = sorted(((m[0], r["id"]) for r, m in pairs if m[0] > MAX_LEN), reverse=True)[:3]
            if over_rows:
                lines.append(f"{'':<20}128 초과 예: {over_rows}")
        lines.append("")
    OUT_SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    OUT_SUMMARY.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(table[0]))
        w.writeheader()
        w.writerows(table)
    print("\n".join(lines))
    print(f"기법별 표: {OUT_CSV.relative_to(ROOT.parent)}")


if __name__ == "__main__":
    main()