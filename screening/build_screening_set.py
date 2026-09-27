"""
T3: 사전 스크리닝 셋 생성.

seeds_screening.jsonl(시드 70건, canary v2 적용)의 text_attack에
17종 변형 × 강도 0.3/0.7을 적용하고, 원문 행을 더해 70 × (17 × 2 + 1) = 2,450행을 만든다.

출력 (screening/ 폴더)
  screening_set.jsonl          측정에 쓰는 본 데이터
  screening_set.csv            엑셀 확인용 (UTF-8 BOM)
  screening_set_manifest.json  재현 정보 (버전, 난수 시드, 입력 해시, 건수)
  screening_set_summary.md     기법 × 강도별 적용률·변경 비율 요약

실행 (레포 루트에서): python screening/build_screening_set.py
"""
import csv
import hashlib
import json
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
from komutator.core import is_syl  # noqa: E402
from komutator.registry import CATEGORY, READABILITY_SKIP, SOURCE, TRANSFORMS, UNIT, mutate  # noqa: E402
from canary import A1_TOKEN, A2_TOKEN, CONFIG  # noqa: E402

MUT_SEED = 20260926          # 변형 난수 시드 (모든 행 공통)
INTENSITIES = (0.3, 0.7)
IN_PATH = HERE / 'seeds_screening.jsonl'


def git_info():
    def run(*args):
        try:
            return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
        except Exception:
            return None
    dirty = run('status', '--porcelain', '--', '*.py', 'rules/')
    return {'commit': run('rev-parse', 'HEAD'), 'describe': run('describe', '--tags', '--always'),
            'dirty': bool(dirty)}


def build_rows(seeds):
    rows = []
    for s in seeds:
        base = {'seed_id': s['id'], 'category': s['category'], 'subtype': s.get('subtype', ''),
                'label': s['label'], 'source_text': s['text_attack']}
        # 원문 행 (난독화 없음, 원문 대비 기준값)
        rows.append({**base, 'row_id': f"{s['id']}__original__0.0", 'technique': 'original',
                     'kotox_category': '', 'source': '', 'intensity': 0.0, 'text': s['text_attack'],
                     'n_syl': sum(is_syl(ch) for ch in s['text_attack']), 'n_cand': 0, 'n_changed': 0, 'unit': '',
                     'change_ratio': 0.0, 'changed': False, 'readability_target': False})
        for tech in TRANSFORMS:
            for it in INTENSITIES:
                m = mutate(tech, s['text_attack'], it, MUT_SEED)
                rows.append({**base, 'row_id': f"{s['id']}__{tech}__{it}", 'technique': tech,
                             'kotox_category': CATEGORY[tech], 'source': SOURCE[tech], 'intensity': it,
                             'text': m['text'], 'n_syl': m['n_syl'], 'n_cand': m['n_cand'],
                             'n_changed': m['n_changed'], 'unit': UNIT[tech],
                             'change_ratio': round(m['n_changed'] / m['n_syl'], 4) if m['n_syl'] else 0.0,
                             'changed': m['changed'],
                             'readability_target': tech not in READABILITY_SKIP})
    return rows


def validate(seeds, rows):
    """문제가 있으면 AssertionError로 중단한다."""
    n_expect = len(seeds) * (len(TRANSFORMS) * len(INTENSITIES) + 1)
    assert len(rows) == n_expect, f'행 수 {len(rows)} != {n_expect}'
    assert len({r['row_id'] for r in rows}) == len(rows), 'row_id 중복'
    assert all(s['canary_version'] == CONFIG['version'] for s in seeds), 'canary 버전 불일치 (canary.py 재실행 필요)'
    for r in rows:
        if r['technique'] == 'original':
            assert r['text'] == r['source_text'], f"{r['row_id']}: 원문 행이 입력과 다름"
        if r['category'] == 'A1_injection':
            assert A1_TOKEN in r['text'], f"{r['row_id']}: canary 토큰 소실"
        assert A2_TOKEN not in r['text'], f"{r['row_id']}: 입력에 비밀 문자열 포함"
    per = defaultdict(int)
    for r in rows:
        per[(r['technique'], r['intensity'])] += 1
    assert all(v == len(seeds) for v in per.values()), '기법·강도별 행 수 불균형'
    return n_expect


def summarize(rows, n_seed):
    by = defaultdict(list)
    for r in rows:
        if r['technique'] != 'original':
            by[(r['technique'], r['intensity'])].append(r)
    text_of = {(r['seed_id'], r['technique'], r['intensity']): r['text'] for r in rows}
    lines = ['| 기법 | 범주 | 단위 | 가독 판정 | 적용률 0.3 | 적용률 0.7 | 평균 변경 비율 0.3 | 평균 변경 비율 0.7 | 0.3=0.7 시드 수 |',
             '| --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    stats = {}
    for tech in TRANSFORMS:
        a, b = by[(tech, 0.3)], by[(tech, 0.7)]
        app = [sum(r['changed'] for r in x) for x in (a, b)]
        ratio = [sum(r['change_ratio'] for r in x) / len(x) for x in (a, b)]
        same = sum(text_of[(r['seed_id'], tech, 0.3)] == text_of[(r['seed_id'], tech, 0.7)] for r in a)
        stats[tech] = {'applied_0.3': app[0], 'applied_0.7': app[1], 'same_0.3_0.7': same}
        lines.append(f"| `{tech}` | {CATEGORY[tech]} | {UNIT[tech]} | {'O' if tech not in READABILITY_SKIP else '생략'} | "
                     f"{app[0]}/{n_seed} | {app[1]}/{n_seed} | {ratio[0]:.3f} | {ratio[1]:.3f} | {same} |")
    return lines, stats


def main():
    seeds = [json.loads(line) for line in IN_PATH.read_text(encoding='utf-8').splitlines() if line.strip()]
    git = git_info()
    if git['dirty']:
        print('⚠️  경고: 커밋되지 않은 코드 변경이 있습니다. 재현성을 위해 커밋 후 생성하세요.')

    rows = build_rows(seeds)
    n = validate(seeds, rows)

    cols = ['row_id', 'seed_id', 'category', 'subtype', 'label', 'technique', 'kotox_category', 'source',
            'intensity', 'text', 'source_text', 'n_syl', 'n_cand', 'n_changed', 'unit', 'change_ratio',
            'changed', 'readability_target']
    with open(HERE / 'screening_set.jsonl', 'w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps({c: r[c] for c in cols}, ensure_ascii=False) + '\n')
    with open(HERE / 'screening_set.csv', 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows({c: r[c] for c in cols} for r in rows)

    lines, stats = summarize(rows, len(seeds))
    cat = defaultdict(int)
    for r in rows:
        cat[r['category']] += 1
    manifest = {
        'created_at': datetime.now().isoformat(timespec='seconds'),
        'rows': n, 'seeds': len(seeds), 'techniques': len(TRANSFORMS), 'intensities': list(INTENSITIES),
        'rows_by_category': dict(cat),
        'readability_targets': sum(r['readability_target'] for r in rows),
        'mutation_seed': MUT_SEED,
        'mutator_git': git, 'canary_version': CONFIG['version'],
        'input_file': IN_PATH.name,
        'input_sha256': hashlib.sha256(IN_PATH.read_bytes()).hexdigest(),
        'per_technique': stats,
    }
    (HERE / 'screening_set_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (HERE / 'screening_set_summary.md').write_text(
        f"# 스크리닝 셋 요약\n\n- {n}행 = 시드 {len(seeds)} × (기법 {len(TRANSFORMS)} × 강도 {list(INTENSITIES)} + 원문)\n"
        f"- 변형기 `{git['describe']}` / canary `{CONFIG['version']}` / 변형 난수 시드 `{MUT_SEED}`\n"
        f"- 적용률: 70건 중 원문과 달라진 행 수 (달라지지 않은 행은 회피·전달 분석에서 제외)\n"
        f"- 평균 변경 비율: 바꾼 위치 수 ÷ 한글 음절 수의 평균 (기법 간 변형량 비교용). "
        f"단위가 공백·음절 쌍·한글 구간인 기법은 비율을 음절 기준 기법과 그대로 비교하지 말 것\n\n" + '\n'.join(lines) + '\n',
        encoding='utf-8')

    print(f"screening_set.jsonl 저장: {n}행 (A1 {cat['A1_injection']} / A2 {cat['A2_leaking']} / 정상 {cat['benign_hard_negative']})")
    print(f"가독 판정 대상 행: {manifest['readability_targets']}  /  변형기 {git['describe']}  /  canary {CONFIG['version']}")
    print('검증 통과: 행 수, row_id 중복 없음, 원문 행 일치, A1 canary 보존, 비밀 문자열 없음\n')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
