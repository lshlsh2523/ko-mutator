"""증강·난독화 평가셋 공통: 문장별 변형 시드와 변형 행 만들기.

시드 규칙: int(sha256("20261003|{id}|{technique}|{intensity}").hexdigest()[:16], 16)
  - 같은 id·기법·강도면 언제 돌려도 같은 결과 (재현 가능)
  - id가 다르면 다른 위치가 바뀜 (_dup1 복제 행도 원본 행과 다르게 변형됨)
변형 행 id: '{원문 id}__{기법}__{강도}'  (스크리닝 셋 row_id와 같은 형식)
n_changed: 실제로 바꾼 수가 아니라 round(후보 수 × 강도)로 정한 변경 예정 수 (mutator-v1 정의).
           그래서 changed=false 행에도 0보다 큰 값이 있을 수 있다.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
sys.path.insert(0, str(REPO))
from komutator.registry import CATEGORY, TRANSFORMS, mutate  # noqa: E402

VARIANT_SEED = 20261003
# 파일에 쓰는 필드: 데이터 형식 제안 5절에서 예고한 9개 (kotox_category, n_cand는 내부 계산용)
FIELDS = ["id", "text", "label", "source",
          "seed_id", "technique", "intensity", "changed", "n_changed"]


def variant_seed(row_id, technique, intensity):
    key = f"{VARIANT_SEED}|{row_id}|{technique}|{intensity}"
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:16], 16)


def make_variant(row, technique, intensity):
    """원문 행 1개 → 변형 행 1개 (라벨·출처는 원문 그대로)."""
    m = mutate(technique, row["text"], intensity, variant_seed(row["id"], technique, intensity))
    return {
        "id": f"{row['id']}__{technique}__{intensity}",
        "text": m["text"],
        "label": row["label"],
        "source": row["source"],
        "seed_id": row["id"],
        "technique": technique,
        "kotox_category": CATEGORY[technique],
        "intensity": intensity,
        "changed": m["changed"],
        "n_cand": m["n_cand"],
        "n_changed": m["n_changed"],
    }


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(rows, path, fields=FIELDS):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps({k: r[k] for k in fields}, ensure_ascii=False) + "\n")


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git_info():
    """dirty: True(커밋 안 된 변경 있음) / False(깨끗함) / None(git 확인 실패)."""
    def run(*args):
        try:
            return subprocess.run(["git", *args], cwd=REPO, capture_output=True,
                                  text=True, check=True, encoding="utf-8").stdout.strip()
        except Exception:
            return None
    status = run("status", "--porcelain", "--", "komutator/", "step1_data/*.py")
    return {"commit": run("rev-parse", "HEAD"), "describe": run("describe", "--tags", "--always"),
            "dirty": None if status is None else bool(status)}


def check_git(git):
    """커밋 안 된 변경이 있거나 git 확인에 실패하면 경고한다."""
    if git["dirty"] is None:
        print("[경고] git 상태를 확인하지 못했습니다. manifest의 dirty가 null로 기록됩니다.")
    elif git["dirty"]:
        print("[경고] 커밋되지 않은 코드 변경이 있습니다. 재현성을 위해 커밋 후 생성하세요.")