"""Step 1 학습 데이터 원본 다운로드 (버전 고정).

사용: 레포 루트에서  python step1_data/download.py

- sources.json 에 적힌 데이터셋을 data/raw/<name>/ 에 받는다.
- 처음 받을 때의 커밋 해시를 data_revision.txt 에 기록하고,
  다음 실행부터는 기록된 해시로 받는다 (팀원 누구나 같은 버전).
- 최신 버전으로 갱신하려면 data_revision.txt 에서 해당 줄을 지우고 다시 실행.
"""
import json
from pathlib import Path

from huggingface_hub import HfApi, snapshot_download

try:  # huggingface_hub 버전에 따라 위치가 다름
    from huggingface_hub.errors import GatedRepoError, RepositoryNotFoundError
except ImportError:
    from huggingface_hub.utils import GatedRepoError, RepositoryNotFoundError

ROOT = Path(__file__).resolve().parent
RAW_DIR = ROOT / "data" / "raw"
REVISION_FILE = ROOT / "data_revision.txt"


def load_revisions():
    """data_revision.txt -> {name: sha}"""
    revisions = {}
    if REVISION_FILE.exists():
        for line in REVISION_FILE.read_text(encoding="utf-8").splitlines():
            if line.strip():
                name, _repo, sha = line.split("\t")
                revisions[name] = sha
    return revisions


def main():
    sources = json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))
    revisions = load_revisions()
    api = HfApi()
    lines, failed = [], []

    for src in sources:
        name, repo = src["name"], src["repo"]
        print(f"\n[{name}] {repo}")
        try:
            sha = revisions.get(name) or api.dataset_info(repo).sha
            snapshot_download(
                repo_id=repo,
                repo_type="dataset",
                revision=sha,
                local_dir=RAW_DIR / name,
                allow_patterns=src.get("allow_patterns"),
            )
        except GatedRepoError:
            print("  !! 접근 승인이 필요합니다. 데이터셋 페이지에서 약관 동의 후 로그인하세요.")
            failed.append(name)
            continue
        except RepositoryNotFoundError:
            print("  !! 저장소를 찾을 수 없습니다. 이름을 확인하세요.")
            failed.append(name)
            continue

        source_tag = "기록된 버전" if name in revisions else "최신 버전"
        print(f"  완료 ({source_tag}): {sha}")
        lines.append(f"{name}\t{repo}\t{sha}")

    # 성공한 것 + 이번에 실패했지만 예전에 기록된 것은 유지
    done = {line.split("\t")[0] for line in lines}
    for src in sources:
        if src["name"] not in done and src["name"] in revisions:
            lines.append(f"{src['name']}\t{src['repo']}\t{revisions[src['name']]}")
    REVISION_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n" + "=" * 40)
    print(f"성공 {len(sources) - len(failed)} / {len(sources)}")
    if failed:
        print("실패:", ", ".join(failed))


if __name__ == "__main__":
    main()