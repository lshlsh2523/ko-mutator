"""
사전 스크리닝 시드 2단계: 뽑기 (층화 추출).

filter_seeds.py가 만든 candidates.jsonl에서
  - A1 25개, A2 25개: 공격 방식(subtype)별 후보 수에 비례해 배분 후 무작위 추출
  - 정상 20개: 단순 무작위 추출
을 수행하고, 선택 결과와 홀드아웃 ID 목록을 저장한다.

배분 규칙: 비례 배분(최대 잔여 방식), 방식마다 최소 1개,
          소수점 잔여가 같으면 후보 수가 많은 방식 → 이름순으로 우선.

실행 (레포 루트에서): python screening/select_seeds.py
"""
import json
import random
from collections import Counter
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent
SEED = 20260926                  # 추출용 난수 시드 (논문에 기록)
QUOTA = {'A1_injection': 25, 'A2_leaking': 25, 'benign_hard_negative': 20}


def allocate(pool, n):
    """pool: {층 이름: 후보 수} → {층 이름: 뽑을 개수} (합계 n)"""
    total = sum(pool.values())
    exact = {k: v * n / total for k, v in pool.items()}
    alloc = {k: max(1, int(x)) for k, x in exact.items()}
    rest = n - sum(alloc.values())
    order = sorted(pool, key=lambda k: (-(exact[k] - int(exact[k])), -pool[k], k))
    for k in order[:rest]:
        alloc[k] += 1
    assert sum(alloc.values()) == n and all(alloc[k] <= pool[k] for k in pool)
    return alloc


def main():
    with open(OUT_DIR / 'candidates.jsonl', encoding='utf-8') as f:
        cands = [json.loads(line) for line in f if line.strip()]
    cands.sort(key=lambda r: r['id'])            # 파일 순서와 무관하게 재현되도록
    rng = random.Random(SEED)

    selected, report = [], []
    for cat, n in QUOTA.items():
        rows = [r for r in cands if r['category'] == cat]
        stratum = (lambda r: r['subtype']) if cat != 'benign_hard_negative' else (lambda r: 'benign')
        pool = Counter(stratum(r) for r in rows)
        alloc = allocate(pool, n)
        for s in sorted(alloc):                  # 층 순서 고정 → 난수 소비 순서 고정
            members = [r for r in rows if stratum(r) == s]
            picked = rng.sample(members, alloc[s])
            selected += sorted(picked, key=lambda r: r['id'])
            report.append((cat, s, pool[s], alloc[s], [r['id'] for r in picked]))

    with open(OUT_DIR / 'seeds_selected.jsonl', 'w', encoding='utf-8') as f:
        for r in selected:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    with open(OUT_DIR / 'holdout_ids.txt', 'w', encoding='utf-8') as f:
        f.write('\n'.join(r['id'] for r in selected) + '\n')

    print(f'추출 시드 {SEED} / 선택 {len(selected)}건\n')
    print(f'{"카테고리":<22}{"층":<22}{"후보":>4}{"선택":>5}  ID')
    for cat, s, p, a, ids in report:
        print(f'{cat:<22}{s:<22}{p:>4}{a:>5}  {", ".join(sorted(ids))}')


if __name__ == '__main__':
    main()