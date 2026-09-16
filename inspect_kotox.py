"""KOTOX 저장소가 우리 환경에서 어떻게 동작하는지 확인한다 (이식 전 점검)."""
import json
import subprocess
import sys
from pathlib import Path

KOTOX = Path('third_party/kotox')

# 1. 패키지를 통째로 import하면 실패하는지 확인 (G2P·openai 등 의존성 때문)
r = subprocess.run([sys.executable, '-c', 'import augment_funtions'],
                   cwd=KOTOX, capture_output=True, text=True, encoding='utf-8')
last = (r.stderr.strip().splitlines() or ['(오류 없음)'])[-1]
print('[1] augment_funtions import:', '성공' if r.returncode == 0 else f'실패 → {last}')

# 2. 이식에 필요한 규칙 사전을 UTF-8로 읽을 수 있는지 확인
replace = json.loads((KOTOX / 'rules/replace.json').read_text(encoding='utf-8'))
iconic = json.loads((KOTOX / 'rules/iconic_dictionary.json').read_text(encoding='utf-8'))
print('[2] replace.json 키와 항목 수:', {k: len(v) for k, v in replace.items()})
print('    vowel_replace_map:', replace['vowel_replace_map'])
print('    yamin_dict 항목 수:', len(iconic['yamin_dict']), '예시:', list(iconic['yamin_dict'].items())[:3])

# 3. hgtk가 설치되어 한글 분해·조립이 되는지 확인
import hgtk  # noqa: E402
print('[3] hgtk 분해:', hgtk.letter.decompose('읽'), '/ 조립:', hgtk.letter.compose('ㅇ', 'ㅣ', 'ㄺ'))