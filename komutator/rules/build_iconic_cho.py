"""komutator/rules/iconic_cho.json 생성 스크립트 (자모 도상 대치용 초성 사전).

KOTOX의 rules/iconic_dictionary.json 중 consonant_dict에서
  - 한 글자이면서 한글이 아닌 후보만 남김 (ㄲ → ㄱㄱ 같은 두 글자, ㄹ → 근 같은 한글 음절 제외)
  - 원본 오류 ㄹ → ㉢(동그라미 ㄷ)을 ㉣으로 바로잡음
사용: python komutator/rules/build_iconic_cho.py <KOTOX의 iconic_dictionary.json 경로>
"""
import json
import re
import sys
from pathlib import Path

src = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))['consonant_dict']
out = {}
for cho, cands in src.items():
    keep = [c for c in cands if len(c) == 1 and not re.fullmatch(r'[가-힣ㄱ-ㅎㅏ-ㅣ]', c)]
    if cho == 'ㄹ':
        keep = ['㉣' if c == '㉢' else c for c in keep]
    if keep:
        out[cho] = sorted(set(keep))
dst = Path(__file__).parent / 'iconic_cho.json'
dst.write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
print(f'{dst} 저장: 초성 {len(out)}종')
