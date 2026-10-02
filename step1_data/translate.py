"""3단계: 영어 -> 한국어 번역 (DeepL).

사용 (레포 루트에서, 키는 환경변수로만):
  export DEEPL_AUTH_KEY="..."
  python step1_data/translate.py --sample 20     # 시험 번역: 출처·라벨별로 고르게 20건
  python step1_data/translate.py                 # 전체 번역 (이미 번역한 id는 건너뜀)
  python step1_data/translate.py --dry-run       # API 없이 흐름만 점검 (가짜 번역, 결과는 별도 파일)

입력: step1_data/data/interim/to_translate.jsonl
결과: step1_data/data/interim/translated.jsonl      (한 줄씩 바로 저장 -> 끊겨도 이어서 가능)
      step1_data/data/reports/translate_review.txt  (원문/번역 나란히, 검수용, git 제외)
      step1_data/reports/translate_log.txt          (실행 기록: 날짜, 건수, 글자 수, 사용량. 커밋 가능)

DeepL Developer 플랜은 계정당 1회 100만 자이고 다시 채워지지 않는다.
그래서 시작 전에 남은 한도를 확인하고, 모자라면 시작하지 않는다.
시험 번역분도 같은 결과 파일에 저장되므로 전체 번역 때 다시 번역하지 않는다(글자 낭비 없음).
"""
import argparse
import datetime as dt
import json
import os
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
IN_FILE = ROOT / "data" / "interim" / "to_translate.jsonl"
OUT_FILE = ROOT / "data" / "interim" / "translated.jsonl"
DRY_OUT_FILE = ROOT / "data" / "interim" / "translated_dryrun.jsonl"
REVIEW_FILE = ROOT / "data" / "reports" / "translate_review.txt"
DRY_REVIEW_FILE = ROOT / "data" / "reports" / "translate_review_dryrun.txt"
LOG_FILE = ROOT / "reports" / "translate_log.txt"

SEED = 20261002
BATCH = 50              # 요청 한 번에 보낼 문장 수
SAFETY_MARGIN = 10_000  # 한도 계산 여유분 (글자)
MAX_RETRY = 5           # 연결이 끊겼을 때 같은 배치를 다시 시도하는 횟수


class FakeTranslator:
    """--dry-run용: API를 부르지 않고 '[KO]'만 붙여 돌려줌"""
    class _R:
        def __init__(self, text):
            self.text, self.detected_source_lang = f"[KO] {text}", "EN"

    def translate_text(self, texts, **_):
        return [self._R(t) for t in texts]

    def get_usage(self):
        return "dry-run (사용량 없음)"


def remaining_chars(translator):
    usage = translator.get_usage()
    if isinstance(usage, str):
        return None, usage
    c = usage.character
    return c.limit - c.count, f"{c.count:,} / {c.limit:,}자 사용"


def load_done(path):
    if not path.exists():
        return set()
    with path.open(encoding="utf-8") as f:
        return {json.loads(line)["id"] for line in f if line.strip()}


def pick_sample(todo, n):
    """출처 x 라벨 묶음마다 고르게 n건"""
    groups = list(todo.groupby(["source", "label"]))
    per = max(1, n // len(groups))
    parts = [g.sample(min(len(g), per), random_state=SEED) for _, g in groups]
    return pd.concat(parts).head(n)


def translate_with_retry(translator, texts):
    """연결 오류(응답이 중간에 끊김 등)면 잠시 쉬었다가 같은 배치를 다시 보냄"""
    for attempt in range(1, MAX_RETRY + 1):
        try:
            return translator.translate_text(
                texts,
                source_lang="EN",
                target_lang="KO",
                preserve_formatting=True,  # 원문의 구두점·대소문자·줄바꿈을 최대한 유지
            )
        except Exception as e:  # deepl.ConnectionException 등
            name = type(e).__name__
            if "Quota" in name or "Authorization" in name or attempt == MAX_RETRY:
                raise
            wait = 10 * attempt
            print(f"  !! {name}: {e} -> {wait}초 후 재시도 ({attempt}/{MAX_RETRY})")
            time.sleep(wait)


def write_review(path_in, review_file):
    rows = [json.loads(l) for l in path_in.open(encoding="utf-8") if l.strip()]
    lines = []
    for r in rows[-200:]:  # 최근 200건까지만
        lines += [f"[{r['id']}] label={r['label']} detected={r['detected_source_lang']}",
                  f"  EN: {r['text_en']}", f"  KO: {r['text']}", ""]
    review_file.parent.mkdir(parents=True, exist_ok=True)
    review_file.write_text("\n".join(lines), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=0, help="시험 번역 건수 (0이면 전체)")
    ap.add_argument("--dry-run", action="store_true", help="API 없이 가짜 번역으로 점검")
    args = ap.parse_args()

    if args.dry_run:
        translator, out_file = FakeTranslator(), DRY_OUT_FILE
        import_version = "dry-run"
    else:
        import deepl
        key = os.environ.get("DEEPL_AUTH_KEY")
        if not key:
            raise SystemExit("DEEPL_AUTH_KEY 환경변수가 없습니다. export DEEPL_AUTH_KEY=\"...\" 후 다시 실행하세요.")
        translator, out_file = deepl.Translator(key), OUT_FILE
        import_version = f"deepl-python {deepl.__version__}"

    data = pd.read_json(IN_FILE, lines=True)
    done = load_done(out_file)
    todo = data[~data["id"].isin(done)]
    if args.sample:
        todo = pick_sample(todo, args.sample)

    need = int(todo["text"].str.len().sum())
    left, usage_text = remaining_chars(translator)
    print(f"번역 대상 {len(todo):,}건 / {need:,}자  (이미 완료 {len(done):,}건)")
    print(f"DeepL 사용량: {usage_text}")
    if left is not None and need + SAFETY_MARGIN > left:
        raise SystemExit(f"!! 남은 한도 {left:,}자가 부족합니다 (필요 {need:,}자 + 여유 {SAFETY_MARGIN:,}자). 중단합니다.")
    if len(todo) == 0:
        print("번역할 문장이 없습니다.")
        return

    out_file.parent.mkdir(parents=True, exist_ok=True)
    n_ok = 0
    with out_file.open("a", encoding="utf-8") as f:
        for start in range(0, len(todo), BATCH):
            batch = todo.iloc[start:start + BATCH]
            results = translate_with_retry(translator, batch["text"].tolist())
            for (_, row), res in zip(batch.iterrows(), results):
                f.write(json.dumps({
                    "id": row["id"], "source": row["source"], "label": int(row["label"]),
                    "pair": row["pair"], "text_en": row["text"], "text": res.text,
                    "detected_source_lang": res.detected_source_lang,
                    "orig_split": row["orig_split"], "orig_row": int(row["orig_row"]),
                }, ensure_ascii=False) + "\n")
            f.flush()  # 배치마다 저장 -> 끊겨도 이어서 가능
            n_ok += len(batch)
            print(f"  {n_ok:,} / {len(todo):,}")

    review_file = DRY_REVIEW_FILE if args.dry_run else REVIEW_FILE
    write_review(out_file, review_file)
    _, usage_after = remaining_chars(translator)
    total_done = len(load_done(out_file))
    log = (f"{dt.datetime.now():%Y-%m-%d %H:%M} | {'sample ' + str(args.sample) if args.sample else 'full'}"
           f"{' (dry-run)' if args.dry_run else ''} | 이번 {n_ok:,}건 {need:,}자 | 누적 {total_done:,}/{len(data):,}건"
           f" | 사용량 {usage_after} | {import_version} | EN->KO, preserve_formatting=True\n")
    if not args.dry_run:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as lf:
            lf.write(log)
    print("\n" + log.strip())
    print(f"검수용 파일: {review_file.relative_to(ROOT.parent)}")


if __name__ == "__main__":
    main()