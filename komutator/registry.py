"""전체 mutator 레지스트리: KG 계열 6 + 신규 3 + KOTOX 이식 8 = 17종.

mutate()는 변형 결과와 함께 변경량(후보 수, 바꾼 수, 변화 여부)을 돌려준다.
"""
from . import kotox_ports, mutators
from .core import is_syl

TRANSFORMS = {**mutators.TRANSFORMS, **kotox_ports.TRANSFORMS}
CANDIDATES = {**mutators.CANDIDATES, **kotox_ports.CANDIDATES}

SOURCE = {
    'jamo_decompose': 'KG', 'chosung': 'KG', 'tensify': 'KG', 'zwsp_inject': 'KG',
    'space_delete': 'KG(분리)', 'space_insert': 'KG(분리)',
    'final_decompose': '신규', 'filler_insert': '신규', 'qwerty': '신규',
    'vowel_replace': 'KOTOX 1-3', 'final_replace': 'KOTOX 1-4',
    'continue_sound': 'KOTOX 3-1', 'yamin_swap': 'KOTOX 5-1',
    'syllable_shuffle': 'KOTOX 11', 'symbol_insert': 'KOTOX 13',
    'romanize': 'KOTOX 음차(규칙화)', 'iconic_swap': 'KOTOX 5-2',
}

# KOTOX 5범주 대응 (선별 근거용)
CATEGORY = {
    'tensify': '음운', 'vowel_replace': '음운', 'final_replace': '음운', 'continue_sound': '음운',
    'yamin_swap': '도상', 'iconic_swap': '도상',
    'romanize': '음차',
    'space_delete': '통사', 'space_insert': '통사', 'syllable_shuffle': '통사',
    'symbol_insert': '화용',
    'jamo_decompose': '표기(자모)', 'chosung': '표기(자모)', 'zwsp_inject': '표기(자모)',
    'final_decompose': '표기(자모)', 'filler_insert': '표기(자모)', 'qwerty': '표기(자판)',
}

# 변경 단위: n_cand·n_changed를 무엇으로 셌는지
UNIT = {n: '음절' for n in TRANSFORMS}
UNIT.update({'space_delete': '공백', 'continue_sound': '음절 쌍', 'syllable_shuffle': '한글 구간'})

# 가독 판정 생략: 원래 글자는 바꾸지 않고 사이에 끼우거나 빼기만 하는 기법
READABILITY_SKIP = {'zwsp_inject', 'space_delete', 'space_insert', 'filler_insert', 'symbol_insert'}

assert set(TRANSFORMS) == set(CANDIDATES) == set(SOURCE) == set(CATEGORY), '기법 목록 불일치'


def mutate(name, text, intensity, seed):
    """변형 1건 + 변경량 기록.

    n_cand: 바꿀 수 있는 위치 수 (단위는 UNIT[name])
    n_changed: 실제로 바꾼 위치 수 (= 후보 수 × 강도의 반올림)
    changed: 결과가 원문과 다른지 (False면 회피·전달 분석에서 제외)
    """
    out = TRANSFORMS[name](text, intensity, seed)
    n_cand = len(CANDIDATES[name](text))
    return {
        'text': out,
        'n_cand': n_cand,
        'n_changed': round(n_cand * intensity),
        'changed': out != text,
        'n_syl': sum(is_syl(ch) for ch in text),
    }
