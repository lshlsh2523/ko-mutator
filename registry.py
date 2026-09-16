"""전체 mutator 레지스트리: KG 계열 6 + 신규 3 + KOTOX 이식 4 = 13종."""
import kotox_ports
import mutators

TRANSFORMS = {**mutators.TRANSFORMS, **kotox_ports.TRANSFORMS}

SOURCE = {
    'jamo_decompose': 'KG', 'chosung': 'KG', 'tensify': 'KG', 'zwsp_inject': 'KG',
    'space_delete': 'KG(분리)', 'space_insert': 'KG(분리)',
    'final_decompose': '신규', 'filler_insert': '신규', 'qwerty': '신규',
    'vowel_replace': 'KOTOX 1-3', 'final_replace': 'KOTOX 1-4',
    'continue_sound': 'KOTOX 3-1', 'yamin_swap': 'KOTOX 5-1',
}