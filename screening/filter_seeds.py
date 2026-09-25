"""
사전 스크리닝 시드 1단계: 걸러내기.

KoreanGuardrail 시드(data/KoreanGuardrail/seeds/)에 제외 기준 E1~E4를 순서대로
적용하고, 남은 후보와 제외 사유를 파일로 저장한다.

실행 (레포 루트에서): python screening/filter_seeds.py
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core import is_syl, split  # noqa: E402

SEED_DIR = ROOT / 'data' / 'KoreanGuardrail' / 'seeds'
OUT_DIR = ROOT / 'screening'
MIN_SYL = 10                     # E4: 한글 음절 최소 개수
PLAIN_CHO = {0, 3, 7, 9, 12}     # 된소리화 후보 초성 (ㄱㄷㅂㅅㅈ)

# E3: 자동 판정 불가 (사람이 읽고 확정한 목록)
E3_EXCLUDE = {
    'atk_0299': '요청 대상 누락 (비교할 예시 없음)',
    'atk_0300': '요청 대상 누락 (초안 없음)',
    'atk_0067': '예/아니오 응답만 요구',
    'atk_0301': 'O/X 응답만 요구',
    'atk_0034': '인코딩 출력 요구 (base64)',
    'atk_0065': '변형 출력 요구 (각 행 첫 글자)',
    'atk_0070': '인코딩 출력 요구 (ROT13)',
    'atk_0285': '인코딩 출력 요구 (답변 base64)',
    'atk_0293': '입력 예고만 있음 (요청 미완결)',
    'atk_0294': '입력 예고만 있음 (요청 미완결)',
}


def load(name):
    with open(SEED_DIR / name, encoding='utf-8') as f:
        return [json.loads(line) for line in f if line.strip()]


def metrics(text):
    syl = [ch for ch in text if is_syl(ch)]
    return {
        'n_syl': len(syl),
        'n_tensify': sum(split(ch)[0] in PLAIN_CHO for ch in syl),   # 된소리화 후보
        'n_final': sum(split(ch)[2] != 0 for ch in syl),             # 받침 분리 후보
    }


def exclusion_reason(row, m):
    """E1~E4를 순서대로 검사해 처음 걸린 사유를 반환 (없으면 None)."""
    if row['source'] == 'template_v1':
        return 'E1 템플릿'
    if row.get('subtype') == 'language_switch':
        return 'E2 공격 지시가 외국어'
    if row['id'] in E3_EXCLUDE:
        return 'E3 ' + E3_EXCLUDE[row['id']]
    if m['n_syl'] < MIN_SYL:
        return f'E4 한글 {m["n_syl"]}음절 (<{MIN_SYL})'
    return None


def main():
    rows = load('attacks.jsonl') + load('benign.jsonl')
    kept, dropped = [], []
    for r in rows:
        m = metrics(r['text'])
        reason = exclusion_reason(r, m)
        (dropped if reason else kept).append({**r, **m, **({'reason': reason} if reason else {})})

    for name, data in [('candidates.jsonl', kept), ('excluded.jsonl', dropped)]:
        with open(OUT_DIR / name, 'w', encoding='utf-8') as f:
            for r in data:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')

    # ---- 보고 ----
    print(f'전체 {len(rows)}건 → 후보 {len(kept)}건, 제외 {len(dropped)}건\n')
    print('[제외 사유별]')
    for k, v in Counter(r['reason'].split()[0] for r in dropped).most_common():
        print(f'  {k}: {v}')
    print('\n[후보: 카테고리별]')
    for k, v in sorted(Counter(r['category'] for r in kept).items()):
        print(f'  {k}: {v}')
    for cat in ['A1_injection', 'A2_leaking']:
        sub = Counter(r['subtype'] for r in kept if r['category'] == cat)
        print(f'\n[후보: {cat} subtype별]  ' + ', '.join(f'{k} {v}' for k, v in sorted(sub.items())))

    # E4 검증: 음절 수는 충분해도 후보가 3개 미만인 기법이 있는지
    print('\n[E4 검증: 후보 3개 미만인 시드 수]')
    for key, label in [('n_tensify', '된소리화'), ('n_final', '받침 분리')]:
        few = [r['id'] for r in kept if r[key] < 3]
        print(f'  {label}: {len(few)}건 {few[:10]}')
    syl = sorted(r['n_syl'] for r in kept)
    print(f'\n[후보 한글 음절 수] 최소 {syl[0]}, 중앙값 {syl[len(syl)//2]}, 최대 {syl[-1]}')


if __name__ == '__main__':
    main()