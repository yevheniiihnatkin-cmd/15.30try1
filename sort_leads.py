#!/usr/bin/env python3
"""
Сортування / фільтрація лідів з CSV-експорту Linked Helper.

Фільтри:
  --max-exp N          загальний досвід в IT до N років (рахується від найранішого
                       organization_start_* до сьогодні)
  --min-exp N          досвід від N років
  --keywords a,b,c     ключові слова стеку (шукає в headline, посаді, summary,
                       skills, описах посад); --match any|all
  --education S        studying | graduated | none
  --course N           курс навчання (лише для тих, хто ще вчиться), --course-max N
  --seniority a,b      trainee, junior, middle, senior, lead, unknown
  --job-seeker         лише з бейджем Open to work
  --keep-unknown       не відсікати лідів, у яких для фільтра немає даних
                       (досвід/освіта не витягнуті з профілю)

Приклади:
  python3 sort_leads.py leads.csv -o out.csv --seniority junior,middle --keywords playwright,cypress
  python3 sort_leads.py leads.csv -o out.csv --max-exp 3 --education studying --course-max 4 --keep-unknown
"""
import argparse
import csv
import re
import sys
from datetime import date

# Технічні / дубльовані колонки, які не потрібні для роботи з лідами
DROP_COLUMNS = {
    "id_type", "public_id_actual_at", "member_id_actual_at", "hash_id",
    "sn_member_id", "sn_hash_id", "r_member_id", "t_hash_id", "avatar_id",
    "public_id_2", "lh_id", "avatar", "mini_profile_actual_at",
    "original_full_name", "original_first_name", "original_last_name",
    "original_headline", "custom_first_name", "custom_last_name",
    "industry_actual_at", "original_current_company", "current_company_custom",
    "original_current_company_position", "current_company_custom_position",
    "current_company_actual_at", "original_mutual_first_fullname",
    "original_mutual_second_fullname", "custom_mutual_first_fullname",
    "custom_mutual_second_fullname", "badges_influencer", "badges_open_link",
    "connected_at", "add_to_target_date", "result_created_at",
    "result_created_at_iso", "invited_date", "message_1_send_at",
    "replied_message_1_send_at", "last_sent_message_send_at",
    "last_received_message_send_at",
}
# Колонки, без яких не можна повторно імпортувати лідів у Linked Helper
ALWAYS_KEEP = {"id", "public_id", "member_id", "profile_url", "full_name"}

SENIORITY_ORDER = ["lead", "senior", "middle", "junior", "trainee", "unknown"]
SENIORITY_PATTERNS = [
    ("lead", r"\b(team\s*lead|tech\s*lead|lead|head of|principal|architect|тімлід|лід)\b"),
    ("senior", r"\b(senior|sr\.?|сеньйор|сеньор)\b"),
    ("middle", r"\b(middle|mid|mid-level|мідл)\b"),
    ("junior", r"\b(junior|jr\.?|джуніор|джун)\b"),
    ("trainee", r"\b(trainee|intern|internship|стажер|стажист|student)\b"),
]

TODAY = date.today()


def parse_date(s):
    """Повертає (рік, місяць) з довільного формату дати LH або None."""
    if not s or not s.strip():
        return None
    m = re.search(r"(\d{4})[-./](\d{1,2})", s)            # 2021-03
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"(\d{1,2})[-./](\d{4})", s)            # 03.2021
    if m:
        return int(m.group(2)), int(m.group(1))
    m = re.search(r"(19|20)\d{2}", s)                     # 2021 / Mar 2021
    if m:
        return int(m.group(0)), 1
    return None


def months_between(a, b):
    return (b[0] - a[0]) * 12 + (b[1] - a[1])


def experience_years(row):
    starts = [parse_date(row.get(f"organization_start_{i}", "")) for i in range(1, 6)]
    starts = [s for s in starts if s]
    if not starts:
        return None
    first = min(starts)
    return round(max(months_between(first, (TODAY.year, TODAY.month)), 0) / 12, 1)


def education_info(row):
    """(status, course): studying/graduated/none, номер курсу або None."""
    found = False
    best = None
    for i in range(1, 4):
        if not (row.get(f"education_{i}") or "").strip():
            continue
        found = True
        start = parse_date(row.get(f"education_start_{i}", ""))
        end = parse_date(row.get(f"education_end_{i}", ""))
        now = (TODAY.year, TODAY.month)
        if end and end <= now:
            status, course = "graduated", None
        elif start:
            # навчальний рік починається у вересні
            course = TODAY.year - start[0] + (1 if TODAY.month >= 9 else 0)
            status, course = "studying", max(course, 1)
        elif end:
            status, course = "studying", None
        else:
            continue
        if status == "studying":
            return status, course
        best = best or (status, course)
    if best:
        return best
    return ("unknown", None) if found else ("none", None)


def seniority(row):
    text = " ".join((row.get(k) or "") for k in
                    ("current_company_position", "headline", "organization_title_1")).lower()
    for level, pat in SENIORITY_PATTERNS:
        if re.search(pat, text):
            return level
    return "unknown"


def search_text(row):
    keys = ["headline", "current_company_position", "summary", "skills",
            "organization_title_1", "organization_title_2",
            "position_description_1", "position_description_2",
            "education_fos_1", "education_fos_2"]
    return " ".join((row.get(k) or "") for k in keys).lower()


def keyword_hits(row, keywords):
    text = search_text(row)
    return [k for k in keywords if re.search(r"(?<![\w])" + re.escape(k) + r"(?![\w])", text)]


def main():
    p = argparse.ArgumentParser(description="Фільтрація лідів Linked Helper")
    p.add_argument("input")
    p.add_argument("-o", "--output", default="leads_filtered.csv")
    p.add_argument("--max-exp", type=float)
    p.add_argument("--min-exp", type=float)
    p.add_argument("--keywords", help="через кому: playwright,java,cypress")
    p.add_argument("--match", choices=["any", "all"], default="any")
    p.add_argument("--education", choices=["studying", "graduated", "none"])
    p.add_argument("--course", type=int, help="точний курс")
    p.add_argument("--course-max", type=int, help="курс не вище N")
    p.add_argument("--seniority", help="через кому: junior,middle,unknown")
    p.add_argument("--job-seeker", action="store_true",
                   help="лише ліди з бейджем Open to work (badges_job_seeker = true)")
    p.add_argument("--keep-unknown", action="store_true",
                   help="залишати лідів без даних для фільтра досвіду/освіти")
    p.add_argument("--keep-all-columns", action="store_true",
                   help="не прибирати технічні та порожні колонки")
    a = p.parse_args()

    with open(a.input, encoding="utf-8-sig", newline="") as f:
        sample = f.read(4096); f.seek(0)
        delim = ";" if sample.count(";") > sample.count(",") else ","
        rows = list(csv.DictReader(f, delimiter=delim))
    if not rows:
        sys.exit("Файл порожній")

    keywords = [k.strip().lower() for k in (a.keywords or "").split(",") if k.strip()]
    levels = {s.strip().lower() for s in (a.seniority or "").split(",") if s.strip()}
    drops = {"exp": 0, "kw": 0, "edu": 0, "sen": 0, "js": 0}
    out = []

    for r in rows:
        exp = experience_years(r)
        edu, course = education_info(r)
        sen = seniority(r)
        hits = keyword_hits(r, keywords) if keywords else []

        if a.max_exp is not None or a.min_exp is not None:
            if exp is None:
                if not a.keep_unknown:
                    drops["exp"] += 1; continue
            elif (a.max_exp is not None and exp > a.max_exp) or \
                 (a.min_exp is not None and exp < a.min_exp):
                drops["exp"] += 1; continue

        if keywords:
            ok = len(hits) == len(keywords) if a.match == "all" else bool(hits)
            if not ok:
                drops["kw"] += 1; continue

        if a.education or a.course or a.course_max:
            if edu == "unknown" or (edu == "none" and a.education != "none"):
                if not a.keep_unknown:
                    drops["edu"] += 1; continue
            else:
                if a.education and edu != a.education:
                    drops["edu"] += 1; continue
                if a.course and course != a.course:
                    drops["edu"] += 1; continue
                if a.course_max and (course is None or course > a.course_max):
                    drops["edu"] += 1; continue

        if a.job_seeker and (r.get("badges_job_seeker") or "").lower() != "true":
            drops["js"] += 1; continue

        if levels and sen not in levels:
            drops["sen"] += 1; continue

        r = dict(r)
        r.update({
            "seniority": sen,
            "exp_years": "" if exp is None else exp,
            "education_status": edu,
            "education_course": course or "",
            "matched_keywords": ", ".join(hits),
        })
        out.append(r)

    # сортування: seniority → досвід (більший вище) → кількість збігів стеку
    out.sort(key=lambda r: (
        SENIORITY_ORDER.index(r["seniority"]),
        -(r["exp_years"] if r["exp_years"] != "" else -1),
        -len(r["matched_keywords"].split(", ")) if r["matched_keywords"] else 0,
    ))

    computed = ["seniority", "exp_years", "education_status", "education_course", "matched_keywords"]
    cols = list(rows[0].keys())
    if not a.keep_all_columns:
        nonempty = {k for k in cols if any((x.get(k) or "").strip() for x in rows)}
        # прибираємо також службову хеш-колонку LH (назва = 32 hex-символи)
        cols = [c for c in cols if c in ALWAYS_KEEP or
                (c not in DROP_COLUMNS and c in nonempty and not re.fullmatch(r"[0-9a-f]{32}", c))]
    fieldnames = ["full_name", "profile_url"] + computed + \
                 [c for c in cols if c not in ("full_name", "profile_url")]

    with open(a.output, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";", extrasaction="ignore")
        w.writeheader()
        w.writerows(out)

    print(f"Всього: {len(rows)} → після фільтрів: {len(out)} → {a.output}")
    print("Відсічено: досвід {exp}, стек {kw}, освіта {edu}, seniority {sen}, job seeker {js}".format(**drops))
    no_exp = sum(1 for r in rows if experience_years(r) is None)
    no_edu = sum(1 for r in rows if not (r.get("education_1") or "").strip())
    if no_exp or no_edu:
        print(f"⚠ Без даних про досвід: {no_exp}, без освіти: {no_edu}. "
              "Додайте в LH кампанію дію 'Visit & extract profile' або використайте --keep-unknown.")


if __name__ == "__main__":
    main()
