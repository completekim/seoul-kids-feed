"""서울 열린데이터광장 → 아이·가족 거리만 거른 작은 목록 (data/feed.json).

수도권 축제 알림 루틴(수 20:37 · 토 08:37)이 이 파일 하나만 읽는다.
서울 API는 거르는 조건 없이 통째로 주고 한 건에 설명문이 수 KB라,
루틴이 직접 받으면 한 회차에 MB 단위가 작업 기억에 들어간다 — 그래서 여기서 먼저 거른다.

  🎟 yeyak   — 공공서비스예약(문화체험·교육강좌) 중 지금 접수 중인 아이·가족 프로그램
  🎭 culture — 문화포털 문화행사 중 앞으로 45일 안에 볼 수 있는 아이·가족 행사

거리 기준점은 루틴과 같은 스타필드 시티 위례.
"""
import json, math, os, re, sys, urllib.parse, urllib.request, datetime as dt

KEY = os.environ.get("SEOUL_API_KEY", "").strip()
BASE = "http://openapi.seoul.go.kr:8088/%s/json/%s/%d/%d/%s"
H = (37.4802, 127.1484)          # 스타필드 시티 위례
MAX_KM = 25.0                    # 서울 끝(은평·강서)까지가 약 25~30 km
CAP = 8                          # 목록마다 가까운 순으로 이만큼만 싣는다 — 루틴이 그대로 메일에 옮긴다
KST = dt.timezone(dt.timedelta(hours=9))
NOW = dt.datetime.now(KST)
TODAY = NOW.date()

KID = re.compile(r"유아|미취학|영유아|아동|어린이|키즈|가족|자녀|부모|엄마|아빠|36개월|[0-9]+개월|만\s?[2-6]\s?세|그림책|동화|인형극")
# 미취학 아이가 갈 수 있다는 표시 — 루틴의 🧒 기준(미취학 눈높이)과 맞춘다
YOUNG = re.compile(r"유아|미취학|영유아|[0-9]+개월|(?<![0-9])[2-6]\s?세|누구나|제한\s?없음|전체|전\s?연령")
OLDER = re.compile(r"초등|[1-6]\s?학년|[7-9]\s?세\s?이상|1[0-9]\s?세\s?이상|청소년|중학생|고등학생|청년")


def get(service, s, e, extra=""):
    url = BASE % (KEY, service, s, e, extra)
    with urllib.request.urlopen(url, timeout=60) as r:
        d = json.loads(r.read().decode("utf-8"))
    v = d.get(service) or {}
    if "row" not in v:
        raise RuntimeError("%s %s" % (service, d.get("RESULT") or v.get("RESULT") or str(d)[:200]))
    return v["row"], int(v.get("list_total_count", 0))


def km(la, lo):
    try:
        la, lo = float(la), float(lo)
    except (TypeError, ValueError):
        return None
    if not (33 < la < 39 and 124 < lo < 132):
        la, lo = lo, la                      # 위경도가 뒤바뀐 행이 있다
        if not (33 < la < 39 and 124 < lo < 132):
            return None
    p1, p2 = math.radians(H[0]), math.radians(la)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lo - H[1]) / 2) ** 2
    return round(2 * 6371 * math.asin(math.sqrt(a)), 1)


def kid_ok(target, title):
    tg = (target or "").strip()
    both = tg + " " + (title or "")
    if "단체" in both and "개인" not in both:        # 학급·어린이집 단체 교육은 가족이 못 간다
        return False
    if "온라인" in both:
        return False
    if re.search(r"미취학[^,.)]{0,12}(불가|제외)", both):
        return False
    if tg.startswith("성인") and not re.search(r"동반|가족|자녀", tg):   # 양육자만 듣는 강좌
        return False
    if OLDER.search(tg) and not YOUNG.search(tg):     # 초등 이상 전용
        return False
    if "양육자" in tg and not re.search(r"동반|와\s?양육자|가족", tg):   # 부모만 듣는 강좌
        return False
    if re.search(r"어르신|청년", tg) and not KID.search(title or ""):    # 가족은 곁다리인 어른 프로그램
        return False
    return bool(KID.search(both))


def clean(s, n):
    s = re.sub(r"<[^>]+>|&[a-z#0-9]+;", " ", s or "")
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def ts(s):
    try:
        return dt.datetime.strptime(s[:16], "%Y-%m-%d %H:%M").replace(tzinfo=KST)
    except (TypeError, ValueError):
        return None


def md(d):
    return "%d/%d" % (d.month, d.day)


def yeyak():
    rows = []
    for svc in ("ListPublicReservationCulture", "ListPublicReservationEducation"):
        s = 1
        while True:
            part, total = get(svc, s, s + 999)
            rows += part
            s += 1000
            if s > total:
                break
    out, cafe, seen, skip = [], [], set(), {"상태": 0, "마감": 0, "대상": 0, "거리": 0, "중복": 0}
    for r in rows:
        if r.get("SVCSTATNM") != "접수중":
            skip["상태"] += 1; continue
        end = ts(r.get("RCPTENDDT"))
        if end is None or end < NOW:
            skip["마감"] += 1; continue
        title = clean(r.get("SVCNM"), 60)
        tgt = clean(r.get("USETGTINFO"), 40)
        if not kid_ok(tgt, title) or r.get("MINCLASSNM") in ("청년정보", "전문/자격증", "단체봉사"):
            skip["대상"] += 1; continue
        k = km(r.get("Y"), r.get("X"))
        if k is None or k > MAX_KM:
            skip["거리"] += 1; continue
        if "키즈카페" in title or "키즈카페" in r.get("MINCLASSNM", "") + r.get("MAXCLASSNM", ""):
            cafe.append({"title": title, "url": r.get("SVCURL", ""), "gu": r.get("AREANM", ""), "km": k, "rcpt_end": md(end)})
            continue                                  # 지점이 수십 곳이라 따로 묶는다
        key = re.sub(r"\(?[0-9]{1,2}월\)?|[0-9]+차|[^가-힣A-Za-z]", "", title)
        if key in seen:
            skip["중복"] += 1; continue
        seen.add(key)
        beg = ts(r.get("RCPTBGNDT"))
        out.append({
            "title": title, "url": r.get("SVCURL", ""), "gu": r.get("AREANM", ""),
            "place": clean(r.get("PLACENM"), 24), "target": tgt, "fee": r.get("PAYATNM", ""),
            "rcpt_end": md(end), "rcpt_end_iso": end.strftime("%Y-%m-%d %H:%M"),
            "rcpt_begin_iso": beg.strftime("%Y-%m-%d %H:%M") if beg else "",
            "use": "%s~%s" % (r.get("SVCOPNBGNDT", "")[5:10].replace("-", "/"), r.get("SVCOPNENDDT", "")[5:10].replace("-", "/")),
            "time": ("%s~%s" % (r.get("V_MIN", ""), r.get("V_MAX", ""))).strip("~"),
            "cat": r.get("MINCLASSNM", ""), "km": k,
        })
    out.sort(key=lambda x: (x["km"], x["rcpt_end_iso"]))
    cafe.sort(key=lambda x: x["km"])
    skip["키즈카페 지점(따로 묶음)"] = len(cafe)
    return out, len(rows), skip, cafe


def culture():
    rows, s = [], 1
    while s <= 8000:                               # 시작일 내림차순 — 1년 넘게 전에 시작한 쪽은 볼 필요 없다
        part, total = get("culturalEventInfo", s, s + 999)
        rows += part
        s += 1000
        if s > total or part[-1].get("STRTDATE", "")[:10] < str(TODAY - dt.timedelta(days=365)):
            break
    horizon = TODAY + dt.timedelta(days=45)
    out, seen, skip = [], set(), {"기간": 0, "대상": 0, "거리": 0, "중복": 0}
    for r in rows:
        try:
            S = dt.date.fromisoformat(r["STRTDATE"][:10]); E = dt.date.fromisoformat(r["END_DATE"][:10])
        except (KeyError, ValueError):
            skip["기간"] += 1; continue
        if E < TODAY or S > horizon or (E - S).days > 90:    # 90일 넘는 상설 전시는 뺀다
            skip["기간"] += 1; continue
        title = clean(r.get("TITLE"), 70)
        tgt = clean(r.get("USE_TRGT"), 40)
        if not kid_ok(tgt, title):
            skip["대상"] += 1; continue
        k = km(r.get("LAT"), r.get("LOT"))
        if k is None or k > MAX_KM:
            skip["거리"] += 1; continue
        key = re.sub(r"[^가-힣A-Za-z0-9]", "", title)
        if key in seen:
            skip["중복"] += 1; continue
        seen.add(key)
        out.append({
            "title": title, "url": r.get("HMPG_ADDR") or r.get("ORG_LINK") or "", "gu": r.get("GUNAME", ""),
            "place": clean(r.get("PLACE"), 24), "target": tgt, "cat": r.get("CODENAME", ""),
            "free": r.get("IS_FREE", ""), "fee": clean(r.get("USE_FEE"), 30),
            "date": md(S) if S == E else "%s~%s" % (md(S), md(E)), "start_iso": str(S), "end_iso": str(E),
            "time": clean(r.get("PRO_TIME"), 20), "registered": r.get("RGSTDATE", "")[:10], "km": k,
        })
    out.sort(key=lambda x: (x["km"], x["start_iso"]))
    return out, len(rows), skip, None


def compact(kind, x):
    """메일 한 줄: t 제목 · u 링크 · g 구 · d 날짜 칸 · k 거리 · x 상세 줄 · soon 3일 안 마감."""
    if kind == "yeyak":
        end = dt.datetime.strptime(x["rcpt_end_iso"], "%Y-%m-%d %H:%M").replace(tzinfo=KST)
        d = "접수 ~" + x["rcpt_end"]
        det = [x["fee"], clean(x["target"], 24), "이용 " + x["use"] if x["use"] != "~" else "", clean(x["time"], 14), clean(x["place"], 16)]
        soon = (end - NOW).days < 3
    else:
        d = x["date"]
        fee = x["fee"] if x["fee"] and x["free"] != "무료" else x["free"]
        det = [clean(fee, 18), clean(x["target"], 24), clean(x["time"], 14), clean(x["place"], 16)]
        soon = False
    det = " · ".join(dict.fromkeys(v for v in det if v and v.strip("~ ")))
    return {"t": x["title"], "u": x["url"], "g": x["gu"], "d": d, "k": x["km"], "x": det, "soon": soon}


def main():
    if not KEY:
        sys.exit("SEOUL_API_KEY 가 없습니다")
    feed = {"generated_kst": NOW.strftime("%Y-%m-%d %H:%M"), "origin": "스타필드 시티 위례", "max_km": MAX_KM}
    for name, fn in (("yeyak", yeyak), ("culture", culture)):
        try:
            items, n, skip, extra = fn()
            feed[name + "_note"] = "받은 %d건 → 거른 뒤 %d건(가까운 %d건만 실음) · 뺀 것 %s" % (
                n, len(items), min(len(items), CAP), " ".join("%s %d" % kv for kv in skip.items()))
            feed[name] = [compact(name, x) for x in items[:CAP]]   # 메일 한 줄에 필요한 것만 — 파일을 작게
            if extra is not None:
                feed["kidscafe"] = [{"t": x["title"], "u": x["url"], "k": x["km"]} for x in extra[:3]]
                feed["kidscafe_count"] = len(extra)
        except Exception as e:                       # 한쪽이 죽어도 다른 쪽은 싣는다
            feed[name] = []
            feed[name + "_note"] = "실패: %s" % str(e)[:200]
    os.makedirs("data", exist_ok=True)
    with open("data/feed.json", "w", encoding="utf-8") as f:
        json.dump(feed, f, ensure_ascii=False, separators=(",", ":"))
    print(feed["yeyak_note"]); print(feed["culture_note"])
    print("feed.json %d bytes" % os.path.getsize("data/feed.json"))


if __name__ == "__main__":
    main()
