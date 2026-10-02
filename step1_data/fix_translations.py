"""4단계 보완: 공격 의미가 사라진 번역만 골라 다시 번역.

사용: 레포 루트에서
  python step1_data/fix_translations.py --dry-run   # 대상만 세기 (API 사용 안 함)
  python step1_data/fix_translations.py             # 재번역 (DEEPL_AUTH_KEY 필요)

대상 (하나라도 해당하면)
  prompt_lost      원문에 prompt가 있는데 번역에 '프롬프트'가 없음 (라벨 무관)
  instruction_lost 공격인데 원문의 instruction(s)가 번역에서 지시/지침/명령/안내로 남지 않음
  password_flip    공격인데 "give/tell/reveal... password"가 '입력'으로 번역됨 (요청 방향이 뒤집힘)

재번역 설정
  context  "사용자가 AI 챗봇에게 보내는 메시지"라는 설명을 함께 보냄 (요청 방향 보존, 사용량에 포함 안 됨)
  glossary prompt -> 프롬프트 등 (EN->KO 용어집이 지원되지 않으면 건너뛰고 context만 사용)

translated.jsonl은 처음 한 번 translated_v1.jsonl로 백업한 뒤 해당 행만 바꾼다.
바뀐 행에는 retranslated=true, retranslate_reason이 붙는다.
"""
import argparse
import json
import os
import re
import shutil
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
TR_FILE = ROOT / "data" / "interim" / "translated.jsonl"
BACKUP = ROOT / "data" / "interim" / "translated_v1.jsonl"
REVIEW = ROOT / "data" / "reports" / "fix_translations_review.txt"
LOG_FILE = ROOT / "reports" / "translate_log.txt"

CONTEXT = "This is a message that a user types to an AI chatbot. Translate it as the user's own message to the chatbot."
GLOSSARY = {"prompt": "프롬프트", "prompts": "프롬프트", "Prompt": "프롬프트",
            "prompt template": "프롬프트 템플릿", "system prompt": "시스템 프롬프트"}
BATCH = 50

EN_PROMPT = re.compile(r"\bprompts?\b", re.IGNORECASE)
EN_INSTR = re.compile(r"\binstructions?\b", re.IGNORECASE)
KO_INSTR = re.compile(r"지시|지침|명령|안내")
EN_PW_ASK = re.compile(r"\b(?:give|tell|reveal|show|share|print|spell|say|provide|what(?:'s| is))\b.{0,25}\bpassword",
                       re.IGNORECASE)


def select(tr):
    reasons = pd.DataFrame(index=tr.index)
    reasons["prompt_lost"] = tr["text_en"].str.contains(EN_PROMPT) & ~tr["text"].str.contains("프롬프트")
    reasons["instruction_lost"] = (tr["label"] == 1) & tr["text_en"].str.contains(EN_INSTR) & ~tr["text"].str.contains(KO_INSTR)
    reasons["password_flip"] = (tr["label"] == 1) & tr["text_en"].str.contains(EN_PW_ASK) & tr["text"].str.contains("입력")
    tr["retranslate_reason"] = reasons.apply(lambda r: ",".join(c for c in reasons.columns if r[c]), axis=1)
    return tr[tr["retranslate_reason"] != ""], reasons


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    tr = pd.read_json(TR_FILE, lines=True)
    if "retranslated" in tr.columns and tr["retranslated"].fillna(False).any():
        raise SystemExit("이미 재번역한 파일입니다. 다시 하려면 translated_v1.jsonl을 translated.jsonl로 복원한 뒤 실행하세요.")
    target, reasons = select(tr)
    chars = int(target["text_en"].str.len().sum())
    print("재번역 대상 (중복 포함 이유별):")
    print(reasons.sum().to_string())
    print(f"합계 {len(target)}건 / {chars:,}자  (공격 {int((target['label'] == 1).sum())}, 정상 {int((target['label'] == 0).sum())})")
    if args.dry_run:
        return

    import deepl
    translator = deepl.Translator(os.environ["DEEPL_AUTH_KEY"])
    usage = translator.get_usage().character
    if chars + 5_000 > usage.limit - usage.count:
        raise SystemExit(f"남은 한도 부족: {usage.limit - usage.count:,}자")

    glossary = None
    try:
        glossary = translator.create_glossary("step1-prompt", source_lang="EN", target_lang="KO", entries=GLOSSARY)
        print("용어집 사용")
    except Exception as e:
        print(f"용어집을 만들 수 없어 context만 사용합니다: {type(e).__name__}: {e}")

    if not BACKUP.exists():
        shutil.copy(TR_FILE, BACKUP)

    new_texts = {}
    try:
        for start in range(0, len(target), BATCH):
            batch = target.iloc[start:start + BATCH]
            kwargs = dict(source_lang="EN", target_lang="KO", preserve_formatting=True, context=CONTEXT)
            if glossary is not None:
                kwargs["glossary"] = glossary
            for attempt in range(1, 6):
                try:
                    results = translator.translate_text(batch["text_en"].tolist(), **kwargs)
                    break
                except Exception as e:
                    if "Quota" in type(e).__name__ or attempt == 5:
                        raise
                    print(f"  !! {type(e).__name__} -> {10 * attempt}초 후 재시도")
                    time.sleep(10 * attempt)
            for idx, res in zip(batch.index, results):
                new_texts[idx] = res.text
            print(f"  {min(start + BATCH, len(target))} / {len(target)}")
    finally:
        if glossary is not None:
            translator.delete_glossary(glossary)

    review = []
    tr["retranslated"] = False
    for idx, text in new_texts.items():
        review += [f"[{tr.at[idx, 'id']}] label={tr.at[idx, 'label']} 이유={tr.at[idx, 'retranslate_reason']}",
                   f"  EN : {tr.at[idx, 'text_en']}", f"  OLD: {tr.at[idx, 'text']}", f"  NEW: {text}", ""]
        tr.at[idx, "text"] = text
        tr.at[idx, "retranslated"] = True
    tr.loc[~tr["retranslated"], "retranslate_reason"] = ""
    tr.to_json(TR_FILE, orient="records", lines=True, force_ascii=False)
    REVIEW.parent.mkdir(parents=True, exist_ok=True)
    REVIEW.write_text("\n".join(review), encoding="utf-8")

    after, _ = select(tr.drop(columns=["retranslate_reason"]).copy())
    u = translator.get_usage().character
    log = (f"{pd.Timestamp.now():%Y-%m-%d %H:%M} | retranslate | {len(new_texts)}건 {chars:,}자 | "
           f"glossary={'yes' if glossary is not None else 'no'}, context=yes | 재번역 후에도 남은 대상 {len(after)}건 | "
           f"사용량 {u.count:,} / {u.limit:,}자\n")
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(log)
    print("\n" + log.strip())
    print(f"전후 비교: {REVIEW.relative_to(ROOT.parent)}")


if __name__ == "__main__":
    main()