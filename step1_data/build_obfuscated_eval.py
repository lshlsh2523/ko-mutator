"""17종 난독화 평가셋 만들기 (test, kg_test).

사용: 레포 루트에서  python step1_data/build_obfuscated_eval.py   (스크립트를 커밋한 뒤 실행)
입력: step1_data/data/final/{test,kg_test}.jsonl
결과:
  step1_data/data/final/obfuscated_test.jsonl        (git 제외) 604 × 17 × 2 = 20,536행
  step1_data/data/final/obfuscated_kg_test.jsonl     (git 제외) 172 × 17 × 2 =  5,848행
  step1_data/reports/obfuscated_eval_summary.txt     기법 × 강도별 적용률 (커밋 가능)
  step1_data/reports/obfuscated_eval_manifest.json   재현 정보 (커밋 가능)

- 변형 행만 담는다 (원문 채점은 test.jsonl, kg_test.jsonl로 따로).
- changed=false 행도 남긴다 (적용률 확인용, 주 결과는 changed=true만 사용).
"""
import json
import sys
from collections import defaultdict
from datetime import datetime

from variants import (FIELDS, ROOT, TRANSFORMS, VARIANT_SEED, check_git, git_info, make_variant,
                      read_jsonl, sha256_file, write_jsonl)

INTENSITIES = (0.3, 0.7)
N_TECHNIQUES = 17
EXPECTED_BASE = {"test": (300, 304), "kg_test": (108, 64)}   # (공격, 정상): 원문 분할 v1
DATA = ROOT / "data" / "final"
JOBS = [("test", DATA / "test.jsonl", DATA / "obfuscated_test.jsonl"),
        ("kg_test", DATA / "kg_test.jsonl", DATA / "obfuscated_kg_test.jsonl")]
OUT_SUMMARY = ROOT / "reports" / "obfuscated_eval_summary.txt"
OUT_MANIFEST = ROOT / "reports" / "obfuscated_eval_manifest.json"


def build(base):
    return [make_variant(r, t, it) for r in base for t in TRANSFORMS for it in INTENSITIES]


def check_base(name, base):
    """입력 원문이 분할 v1과 같은지 (건수, 라벨, id 중복)."""
    n_atk = sum(r["label"] == 1 for r in base)
    got = (n_atk, len(base) - n_atk)
    assert got == EXPECTED_BASE[name], f"{name}: 입력 (공격, 정상) {got} != {EXPECTED_BASE[name]}"
    assert len({r["id"] for r in base}) == len(base), f"{name}: 원문 id 중복"


def validate(name, base, rows):
    """메모리의 변형 행 검사. 문제가 있으면 AssertionError로 멈춘다."""
    assert len(TRANSFORMS) == N_TECHNIQUES, f"기법 수 {len(TRANSFORMS)} != {N_TECHNIQUES}"
    n_expect = len(base) * len(TRANSFORMS) * len(INTENSITIES)
    assert len(rows) == n_expect, f"{name}: 행 수 {len(rows)} != {n_expect}"
    assert len({r["id"] for r in rows}) == len(rows), f"{name}: id 중복"
    parent = {r["id"]: r for r in base}
    assert not ({r["id"] for r in rows} & set(parent)), f"{name}: 변형 id가 원문 id와 겹침"
    for r in rows:
        p = parent[r["seed_id"]]
        assert (r["label"], r["source"]) == (p["label"], p["source"]), f"{r['id']}: 라벨·출처 불일치"
        assert r["changed"] == (r["text"] != p["text"]), f"{r['id']}: changed 값 오류"
        assert r["text"].strip(), f"{r['id']}: 빈 문장"
        assert r["id"] == f"{r['seed_id']}__{r['technique']}__{r['intensity']}", f"{r['id']}: id 형식 오류"
    per = defaultdict(int)
    for r in rows:
        per[(r["technique"], r["intensity"])] += 1
    assert set(per.values()) == {len(base)}, f"{name}: 기법·강도별 행 수 불균형"


def verify_file(name, path, n_expect):
    """저장한 파일을 다시 읽어 줄 수와 필드를 확인한다."""
    saved = read_jsonl(path)
    assert len(saved) == n_expect, f"{name}: 파일 행 수 {len(saved)} != {n_expect}"
    bad = [r["id"] for r in saved if list(r) != FIELDS]
    assert not bad, f"{name}: 필드가 {FIELDS}와 다른 행 {len(bad)}개 (예: {bad[:3]})"
    return saved


def summarize(name, base, rows):
    by = defaultdict(list)
    for r in rows:
        by[(r["technique"], r["intensity"])].append(r)
    n_atk = sum(r["label"] == 1 for r in base)
    lines = [f"[{name}] 원문 {len(base)}건 (공격 {n_atk} / 정상 {len(base) - n_atk}) → 변형 {len(rows)}행",
             f"{'기법':<18}{'범주':<8}{'적용률 0.3':>14}{'적용률 0.7':>14}"]
    stats = {}
    for t in TRANSFORMS:
        cells = []
        for it in INTENSITIES:
            c = sum(r["changed"] for r in by[(t, it)])
            cells.append(c)
            stats[f"{t}__{it}"] = c
        lines.append(f"{t:<18}{rows and by[(t, 0.3)][0]['kotox_category']:<8}"
                     + "".join(f"{c:>8}/{len(base)} ({c / len(base):.0%})" for c in cells))
    n_changed = sum(r["changed"] for r in rows)
    lines.append(f"changed=true 합계: {n_changed}/{len(rows)} ({n_changed / len(rows):.1%})")
    return lines, stats


def main():
    sys.stdout.reconfigure(encoding="utf-8")   # 윈도우(cp949) 터미널에서도 출력이 멈추지 않게
    git = git_info()
    check_git(git)
    report, manifest_files, saved_texts = [], {}, {}
    for name, src, dst in JOBS:
        base = read_jsonl(src)
        check_base(name, base)
        rows = build(base)
        validate(name, base, rows)
        write_jsonl(rows, dst)
        saved_texts[name] = {r["text"] for r in verify_file(name, dst, len(rows))}
        lines, stats = summarize(name, base, rows)
        report += lines + [""]
        manifest_files[name] = {"input": src.name, "input_sha256": sha256_file(src),
                                "output": dst.name, "output_sha256": sha256_file(dst),
                                "base_rows": len(base), "rows": len(rows), "changed_by_cell": stats}
        print(f"{dst.name} 저장: {len(rows)}행 (검증 통과)")
    overlap = saved_texts["test"] & saved_texts["kg_test"]
    assert not overlap, f"test ↔ kg_test 변형 사이 완전히 같은 문장 {len(overlap)}개 (예: {list(overlap)[:2]})"
    print("파일 재확인 통과: 행 수, 필드 9개, test ↔ kg_test 변형 간 같은 문장 0개")
    OUT_SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    OUT_SUMMARY.write_text("\n".join(report), encoding="utf-8")
    OUT_MANIFEST.write_text(json.dumps({
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "techniques": list(TRANSFORMS), "intensities": list(INTENSITIES),
        "variant_seed": VARIANT_SEED,
        "seed_rule": 'int(sha256("{VARIANT_SEED}|{id}|{technique}|{intensity}").hexdigest()[:16], 16)',
        "fields": FIELDS, "mutator_git": git, "files": manifest_files,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("\n" + "\n".join(report))


if __name__ == "__main__":
    main()