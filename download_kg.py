"""KoreanGuardrail 데이터셋 다운로드 (버전 고정)."""
from pathlib import Path

from huggingface_hub import HfApi, snapshot_download

REPO = "kimchunsik03/KoreanGuardrail"

# 1. 현재 최신 버전(커밋 해시) 확인
sha = HfApi().dataset_info(REPO).sha
print("커밋 해시:", sha)

# 2. 그 버전으로 고정해서 다운로드
path = snapshot_download(
    repo_id=REPO,
    repo_type="dataset",
    revision=sha,
    local_dir="data/KoreanGuardrail",
)
print("저장 위치:", path)

# 3. 버전을 파일로 기록 (논문·재현용)
Path("data_revision.txt").write_text(f"{REPO} {sha}\n", encoding="utf-8")
