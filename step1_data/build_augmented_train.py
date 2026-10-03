"""증강 학습 데이터 만들기 (train에만 적용).

사용: 레포 루트에서  python step1_data/build_augmented_train.py   (스크립트를 커밋한 뒤 실행)
입력: step1_data/data/final/train.jsonl (+ 누수 확인용 valid, test, kg_test, obfuscated_*)
결과:
  step1_data/data/final/augmented_train.jsonl          (git 제외) 원문 4,809행 + 변형
  step1_data/reports/augmented_train_summary.txt       건수, 길이 KS (커밋 가능)
  step1_data/reports/augmented_train_manifest.json     재현 정보 (커밋 가능)

조건 (0단계 결정, 노션 6절):
- 기법: yamin_swap 0.7, symbol_insert 0.3 (T9b ambiguous 보충 2종)
- 공격·정상 모두, 원문 1개당 기법별 변형 1개 (최대 3배)
- changed=false 변형은 제외 (원문과 같은 문장)
- 길이 보정 복제 행(_dup1)도 변형. 시드가 id 기반이라 원본 행과 다른 위치가 바뀜
- 원문 행: 변형 필드(seed_id, technique, intensity, changed, n_changed)는 null
- 파일 안 순서는 고정 시드로 섞음
"""
import json
import random
import sys
from collections import Counter
from datetime import datetime

import numpy as np

from variants import (FIELDS, ROOT, VARIANT_SEED, check_git, git_info, make_variant,
                      read_jsonl, sha256_file, write_jsonl)

sys.path.insert(0, str(ROOT))
from sample_normals import ks_stat  # noqa: E402

AUG = [("yamin_swap", 0.7), ("symbol_insert", 0.3)]
EXPECTED_TRAIN = (2401, 2408, 373)          # (공격, 정상, _dup1): 원문 분할 v1
DATA = ROOT / "data" / "final"
IN_TRAIN = DATA / "train.jsonl"
OUT = DATA / "augmented_train.jsonl"
LEAK_FILES = ["valid.jsonl", "test.jsonl", "kg_test.jsonl",
              "obfuscated_test.jsonl", "obfuscated_kg_test.jsonl"]
OUT_SUMMARY = ROOT / "reports" / "augmented_train_summary.txt"
OUT_MANIFEST = ROOT / "reports" / "augmented_train_manifest.json"
NULL_VARIANT = {"seed_id": None, "technique": None, "intensity": None, "changed": None, "n_changed": None}


def check_base(base):
    n_atk = sum(r["label"] == 1 for r in base)
    n_dup = sum(r["id"].endswith("_dup1") for r in base)
    got = (n_atk, len(base) - n_atk, n_dup)
    assert got == EXPECTED_TRAIN, f"train (공격, 정상, _dup1) {got} != {EXPECTED_TRAIN}"
    assert len({r["id"] for r in base}) == len(base), "train 원문 id 중복"


def build(base):
    all_variants = [make_variant(r, t, it) for r in base for t, it in AUG]
    variants = [v for v in all_variants if v["changed"]]
    originals = [{**{k: r[k] for k in ("id", "text", "label", "source")}, **NULL_VARIANT} for r in base]
    rows = originals + variants
    random.Random(VARIANT_SEED).shuffle(rows)
    return rows, variants, len(all_variants) - len(variants)


def validate(base, rows, variants):
    parent = {r["id"]: r for r in base}
    ids = [r["id"] for r in rows]
    assert len(set(ids)) == len(ids), "id 중복"
    assert len(rows) == len(base) + len(variants), "행 수 불일치"
    allowed = set(AUG)
    for v in variants:
        p = parent[v["seed_id"]]
        assert (v["technique"], v["intensity"]) in allowed, f"{v['id']}: 허용되지 않은 기법·강도"
        assert (v["label"], v["source"]) == (p["label"], p["source"]), f"{v['id']}: 라벨·출처 불일치"
        assert v["changed"] and v["text"] != p["text"], f"{v['id']}: 원문과 같은 변형"
        assert v["text"].strip(), f"{v['id']}: 빈 문장"
        assert v["id"] == f"{v['seed_id']}__{v['technique']}__{v['intensity']}", f"{v['id']}: id 형식 오류"
    label_of = {}
    for r in rows:
        assert label_of.setdefault(r["text"], r["label"]) == r["label"], f"같은 문장에 다른 라벨: {r['text'][:40]}"


def check_leak(rows):
    """증강 train의 문장이 다른 분할·평가셋에 그대로 있으면 멈춘다 (평가 누수)."""
    texts = {r["text"] for r in rows}
    result = {}
    for name in LEAK_FILES:
        path = DATA / name
        if not path.exists():
            result[name] = "파일 없음 (확인 생략)"
            continue
        n = len(texts & {r["text"] for r in read_jsonl(path)})
        assert n == 0, f"누수: augmented_train ↔ {name} 같은 문장 {n}개"
        result[name] = 0
    return result


def verify_file(path, n_expect):
    saved = read_jsonl(path)
    assert len(saved) == n_expect, f"파일 행 수 {len(saved)} != {n_expect}"
    bad = [r["id"] for r in saved if list(r) != FIELDS]
    assert not bad, f"필드가 {FIELDS}와 다른 행 {len(bad)}개 (예: {bad[:3]})"


def length_ks(rows):
    """xTRam1 짝의 공격·정상 길이(len(text)) KS: 전체 / 원문 / 변형 / 기법별."""
    def ks(sel):
        x = [r for r in rows if r["source"] == "xtram1" and sel(r)]
        a = np.array([len(r["text"]) for r in x if r["label"] == 1])
        b = np.array([len(r["text"]) for r in x if r["label"] == 0])
        return round(ks_stat(a, b), 3)
    out = {"전체": ks(lambda r: True), "원문": ks(lambda r: r["seed_id"] is None),
           "변형": ks(lambda r: r["seed_id"] is not None)}
    for t, _ in AUG:
        out[t] = ks(lambda r, t=t: r["technique"] == t)
    return out


def summarize(base, rows, variants, n_dropped, ks, leak):
    lab = Counter(r["label"] for r in rows)
    per_seed = Counter(Counter(v["seed_id"].removesuffix("_dup1") for v in variants).values())
    lines = [f"원문 {len(base)}행 (공격 {EXPECTED_TRAIN[0]} / 정상 {EXPECTED_TRAIN[1]}, _dup1 {EXPECTED_TRAIN[2]})",
             f"변형 {len(variants)}행 (changed=false로 제외 {n_dropped}행)",
             f"증강 train 합계 {len(rows)}행 (공격 {lab[1]} / 정상 {lab[0]})", "",
             "[기법별 변형 행]  기법 강도: 공격 / 정상 (제외)"]
    for t, it in AUG:
        v = [x for x in variants if x["technique"] == t]
        a = sum(x["label"] == 1 for x in v)
        lines.append(f"  {t} {it}: {a} / {len(v) - a}  (제외 {len(base) - len(v)})")
    lines += ["", "[라벨_출처별 행]  원문 → 증강 합계"]
    key = lambda r: f"{'공격' if r['label'] == 1 else '정상'}_{r['source']}"  # noqa: E731
    k_base, k_all = Counter(map(key, base)), Counter(map(key, rows))
    for k in sorted(k_base):
        lines.append(f"  {k}: {k_base[k]} → {k_all[k]} ({k_all[k] / k_base[k]:.2f}배)")
    lines += ["", f"[xTRam1 짝 길이 KS, len(text) 기준]  {ks}  (원문 train 보정값 0.035)",
              f"[원문 그룹당 변형 행 수 (_dup1은 원본과 합침)]  {dict(sorted(per_seed.items()))}",
              f"[누수 확인: 같은 문장 수]  {leak}"]
    return lines


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    git = git_info()
    check_git(git)
    base = read_jsonl(IN_TRAIN)
    check_base(base)
    rows, variants, n_dropped = build(base)
    validate(base, rows, variants)
    leak = check_leak(rows)
    write_jsonl(rows, OUT)
    verify_file(OUT, len(rows))
    print(f"{OUT.name} 저장: {len(rows)}행 (검증 통과)")
    ks = length_ks(rows)
    lines = summarize(base, rows, variants, n_dropped, ks, leak)
    OUT_SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    OUT_SUMMARY.write_text("\n".join(lines) + "\n", encoding="utf-8")
    OUT_MANIFEST.write_text(json.dumps({
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "augment": [{"technique": t, "intensity": it} for t, it in AUG],
        "variant_seed": VARIANT_SEED,
        "seed_rule": 'int(sha256("{VARIANT_SEED}|{id}|{technique}|{intensity}").hexdigest()[:16], 16)',
        "shuffle_seed": VARIANT_SEED, "fields": FIELDS, "mutator_git": git,
        "input": IN_TRAIN.name, "input_sha256": sha256_file(IN_TRAIN),
        "output": OUT.name, "output_sha256": sha256_file(OUT),
        "rows": len(rows), "variants": len(variants), "dropped_unchanged": n_dropped,
        "length_ks_xtram1": ks, "leak_check": leak,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()