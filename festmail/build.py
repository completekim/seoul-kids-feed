"""수도권 축제 알림 — 원장(고르기 아티팩트 feed/current) 합치기 + 메일 조립 (v17, 2026-10-01).

원칙: **아티팩트 DB가 원장이고 메일은 그 인쇄본이다.**
  루틴은 ① 원장(feed/current)과 표시(marks)를 읽고 ② 이번 조회(TourAPI·서울 거름망·날씨)를 받아
  ③ 이 스크립트로 합쳐 원장을 먼저 갱신한 뒤 ④ 같은 데이터로 찍은 HTML을 메일로 보낸다.
  직전 메일을 Gmail에서 다시 읽는 일은 없다 — NEW·상세 줄 재사용·제외 판단이 전부 원장에 남는다.

  왜 바꿨나(2026-10-01): 포천 한탄강 가든페스타(9/12~11/1)가 관광공사 목록에서 내려가자 메일·고르기에서
  조용히 사라졌다. 원장이 있으면 끝나는 날 전까지 「목록에서 빠짐」 표시로 남기고, 취소 여부는 사용자가 고르기에서 ✕로 정한다.

쓰는 법(루틴 안, 작업 폴더는 --tmp, 기본 /tmp):
  plan : 원장+조회를 합치고, 상세를 새로 불러야 할 행사(조회|cid|제목)와 새로 들어온 제목(판단용)을 찍는다.
  mail : 상세(d.txt)·제외(excl.txt)·🧒 추가(kid.txt)를 반영해 feed_art.json(원장)·mail.html·subject.txt·to.json·report.txt 를 쓴다.

입력 파일(--tmp 아래):
  f.txt        TourAPI 행 — 지역|title|addr1|eventstartdate|eventenddate|mapx|mapy|lclsSystm2|contentid
  w.json       Open-Meteo 응답 원문(daily)            — 없으면 날씨 줄 생략
  sk.json      completekim/seoul-kids-feed data/feed.json — 없으면 🎟·🎭 상자에 안내 한 줄
  led/feed/current.json   ArtifactData get(out_dir=led)로 받은 원장 — 없으면 첫 실행(NEW 생략)
  marks/marks/*.json      ArtifactData list(out_dir=marks)로 받은 📌·✕ 표시
  visits/visits/*.json    (선택) ✓ 다녀옴 {t, d, ds:[날짜…]} — 다녀온 날이 행사 시작 전이면 「작년에 갔던 곳」
  go/go/*.json            (선택) 🚗 간다 {t, e} — 메일 맨 위 「이번에 갈 곳」 상자로 옮겨 크게
  d.txt        (mail) 새로 조회한 상세 — cid|요금|시간|장소|아이 거리
  excl.txt     (mail) 본문에서 뺄 것 — cid|사유 (수완 나이 제한·타지역 홍보 장터). 원장 skipped 에 남아 다음 회차에도 유지
  kid.txt      (mail) 제목만으로는 안 걸리는 🧒(지역 마스코트 등) — cid 한 줄씩. 원장에 남는다
  fail.txt     (선택) 수집 실패 지역 — 지역|사유

행사 정리(2026-10-10 추가 — 고르기 화면의 「📋 정리」 펼침):
  plan 이 환경변수 TOURAPI_KEY 가 있으면, 원장에 정리(i)가 없는 TourAPI 행사마다 detailCommon2·detailIntro2·detailInfo2 를
  직접 불러 칸별로 정리해 info.json 에 남기고, mail 이 그걸 원장 항목의 i 칸에 붙인다. 한 번 정리한 행사는 원장에 남아 다시 부르지 않는다.
  i = {v, at, time, place, addr, cast(출연), fee, age, prog(프로그램), about(소개), tel, home:[주소…], host(주최), book(예매처)}
  모델 판단이 끼지 않는다 — 관광공사 원문 칸을 그대로(태그만 지우고 길이만 자른다) 옮긴다. 출연은 detailInfo2 의 「출연」 칸.
"""
import argparse, glob, hashlib, html, json, math, os, re, subprocess, sys, urllib.parse, urllib.request, datetime as dt
from concurrent.futures import ThreadPoolExecutor

KST = dt.timezone(dt.timedelta(hours=9))
H = (37.4802, 127.1484)      # 스타필드 시티 위례 (경기 하남시 위례대로 200, TourAPI 좌표)
ART = "https://claude.ai/artifact/GSTWb27YKAW3e3m4X71nkn"
LEDGER_V = 17
WINDOW = 21                  # 조회 창 오늘~+21일
PERM_DAYS = 60               # 기간일수 > 60 → 상설
BIRTH = (2024, 1)            # 수완 2024년 1월생

# 문체부 문화관광축제(구석구석 축제 사이트 수도권 11건, 2026-09-27 확인) + 2026 글로벌축제. festivalgrade 칸은 전부 비어 있어 못 쓴다.
BIG = {'부천국제만화': '⭐ 문화관광축제', '수원화성문화제': '🌏 글로벌축제', '시흥갯골축제': '⭐ 문화관광축제', '바우덕이축제': '⭐ 문화관광축제',
       '오곡나루축제': '⭐ 문화관광축제', '연천구석기축제': '⭐ 문화관광축제', '이천도자기축제': '⭐ 문화관광축제', '화성뱃놀이': '⭐ 문화관광축제',
       '강동선사문화축제': '⭐ 문화관광축제', '부평풍물대축제': '⭐ 문화관광축제', '인천펜타포트': '🌏 글로벌축제'}
# 공휴일 표 — 이 표 밖의 공휴일을 지어내지 않는다. 2026-12-01 이후엔 정비에 갱신 경고.
HOLI = {'2026-10-03': '개천절', '2026-10-05': '개천절', '2026-10-09': '한글날', '2026-12-25': '성탄절'}
HOLI_UNTIL = '2026-12-01'
BIG_UNTIL = '2027-01-01'

KID_TITLE = re.compile('과학|선사|아이|어린이|키즈|가족|인형|동물|공룡|서커스|마술|놀이')
INDOOR = re.compile('박물관|미술관|전시관|과학관|아트홀|아트센터|극장|공연장|도서관|문화회관|키즈카페|실내')
WET = ('💧', '🌧', '🌦', '⛈')
CAT = {'EV01': '축제', 'EV02': '공연', 'EV03': '전시'}
WD = '월화수목금토일'

def n(s):
    return re.sub('20[0-9][0-9]|제[0-9]+회|[^0-9A-Za-z가-힣]', '', s or '').lower()

def key(t):
    return hashlib.sha1(n(t).encode()).hexdigest()[:10]

def km(la, lo):
    p1, p2 = math.radians(H[0]), math.radians(la); dp = p2 - p1; dl = math.radians(lo - H[1])
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def iso(s):  # YYYYMMDD → date
    return dt.date(int(s[:4]), int(s[4:6]), int(s[6:8]))

def md(d):
    return '%d/%d' % (d.month, d.day)

def esc(s):
    return html.escape(str(s or ''), quote=True)

def is_regular(now):
    t = now.hour * 60 + now.minute
    return now.weekday() in (2, 4) and 16 * 60 <= t <= 18 * 60

def last_regular_before(now):
    """now 직전의 정기 회차 시각(수 16:57 / 금 16:57)."""
    for back in range(0, 8):
        d = now - dt.timedelta(days=back)
        for wd, hh, mm in ((2, 16, 57), (4, 16, 57)):
            if d.weekday() == wd:
                c = d.replace(hour=hh, minute=mm, second=0, microsecond=0)
                if c <= now: return c
    return now - dt.timedelta(days=7)

def suwan_months(today):
    return (today.year - BIRTH[0]) * 12 + today.month - BIRTH[1] - (1 if today.day < 15 else 0)

def read_json(p):
    try:
        with open(p, encoding='utf-8') as f: return json.load(f)
    except Exception: return None

def unwrap(d):  # ArtifactData 가 저장한 문서는 본문이 그대로거나 data 안에 있다
    if isinstance(d, dict) and 'data' in d and isinstance(d['data'], dict) and 'items' not in d and 's' not in d: return d['data']
    return d

def lines(p):
    try:
        with open(p, encoding='utf-8') as f: return [l.rstrip('\n') for l in f if l.strip()]
    except FileNotFoundError: return []

# ───────────────────────── 행사 정리(i) — TourAPI 상세 3종 ─────────────────────────
INFO_V = 1
TOUR = 'https://apis.data.go.kr/B551011/KorService2/'
CAP = {'time': 120, 'place': 120, 'addr': 120, 'cast': 500, 'fee': 500, 'age': 80, 'prog': 1000, 'about': 400, 'tel': 120, 'host': 80, 'book': 200}

def clean(s):
    s = re.sub(r'<br\s*/?>', '\n', str(s or ''), flags=re.I)
    s = html.unescape(re.sub(r'</?[A-Za-z][A-Za-z0-9]*(?:\s[^<>]*)?/?>', '', s)).replace('\xa0', ' ')   # 「<문화가 흐르는 서울광장>」 같은 한글 꺾쇠는 살린다
    s = '\n'.join(re.sub(r'[ \t]+', ' ', l).strip() for l in s.split('\n'))
    return re.sub(r'\n{3,}', '\n\n', s).strip()

def tidy(s):
    """한 줄로 뭉쳐 온 요금표(「[정가] - 1일권 … [할인] - …」)를 항목마다 줄바꿈. 이미 줄이 나뉜 글은 그대로."""
    if '\n' in s or len(s) < 40: return s
    s = re.sub(r'\s*(\[[^\]]{1,30}\])\s*', r'\n\1\n', s)
    s = re.sub(r'(?:^|\s+)-\s+(?=\S)', '\n- ', s)                       # 「… - 2일권」
    s = re.sub(r'(?<=[가-힣%)])-\s+(?=\S)|(?<=[원%)])-(?=\S)', '\n- ', s)   # 「12,000원- 청소년」「지참- 소극장」 (전화번호·날짜의 - 는 그대로)
    s = re.sub(r'\s*※\s*', '\n※ ', s)
    return re.sub(r'\n{2,}', '\n', s).strip()

def cut(s, n):
    return s if len(s) <= n else s[:n - 1].rstrip() + '…'

def get_json(url):
    """curl 이 먼저(루틴 샌드박스는 curl 이 허용 목록을 통과한다), 안 되면 urllib."""
    try:
        r = subprocess.run(['curl', '-sS', '--max-time', '25', url], capture_output=True, timeout=30)
        if r.returncode == 0 and r.stdout.strip(): return json.loads(r.stdout)
    except Exception: pass
    try:
        with urllib.request.urlopen(url, timeout=25) as f: return json.load(f)
    except Exception: return None

def tour_items(op, key, cid, typ=True):
    q = {'serviceKey': key, 'MobileOS': 'ETC', 'MobileApp': 'festalert', '_type': 'json', 'contentId': cid}
    if typ: q['contentTypeId'] = 15
    d = get_json(TOUR + op + '?' + urllib.parse.urlencode(q))
    if not isinstance(d, dict): return None          # 호출 실패 — 다음 회차에 다시
    body = (d.get('response') or {}).get('body') or {}
    it = body.get('items') or {}
    it = it.get('item', []) if isinstance(it, dict) else []
    return it if isinstance(it, list) else [it]

def homes(s):
    out = []
    for u in re.findall(r'(https?://[^\s<>"\')]+|www\.[^\s<>"\')]+|[A-Za-z0-9.-]+\.(?:com|kr|net|org|co\.kr|or\.kr|go\.kr)(?:/[^\s<>"\')]*)?)', s or ''):
        u = u.rstrip('.,;')
        if not u.startswith('http'): u = 'https://' + u
        if u not in out: out.append(u)
    return out[:3]

def tour_info(key, cid, nowtxt):
    com, intro, det = tour_items('detailCommon2', key, cid, False), tour_items('detailIntro2', key, cid), tour_items('detailInfo2', key, cid)
    if com is None or intro is None or det is None: return None
    c, t = (com or [{}])[0], (intro or [{}])[0]
    if not com and not intro: return {'v': INFO_V, 'at': nowtxt, 'none': True}   # 관광공사가 contentid 째 지운 행사
    di = {}
    for x in det:
        nm, tx = clean(x.get('infoname')), clean(x.get('infotext'))
        if nm and tx and nm not in di: di[nm] = tx
    prog = clean(t.get('program')) or di.get('행사내용', '')
    sub = clean(t.get('subevent'))
    if sub and sub not in prog: prog = (prog + '\n\n[부대행사]\n' + sub).strip()
    cast = di.get('출연', '')
    if not cast:   # 「출연」 칸이 없으면 프로그램 안의 라인업·출연 줄만
        m = re.search(r'(?:라인업|출연진|출연)\s*(?:[:：]|\n)\s*-?\s*([^\n]{2,300})', prog)
        if m: cast = m.group(1).strip(' -')
    age = clean(t.get('agelimit'))
    i = {'v': INFO_V, 'at': nowtxt, 'time': clean(t.get('playtime')), 'place': clean(t.get('eventplace')), 'addr': clean(c.get('addr1')),
         'cast': cast, 'fee': tidy(clean(t.get('usetimefestival'))), 'age': age, 'prog': prog, 'about': clean(c.get('overview')) or di.get('행사소개', ''),
         'tel': ' '.join(x for x in (clean(c.get('telname')), clean(c.get('tel')) or clean(t.get('sponsor1tel'))) if x),
         'home': homes(clean(c.get('homepage')) + ' ' + clean(t.get('eventhomepage'))), 'host': clean(t.get('sponsor1')), 'book': clean(t.get('bookingplace'))}
    for k, n0 in CAP.items(): i[k] = cut(i[k], n0)
    return {k: v for k, v in i.items() if v not in ('', [])}

def fetch_infos(tmp, items, nowtxt, limit=160):
    """원장에 정리(i)가 없는 TourAPI 행사만 부른다. 결과는 tmp/info.json {cid: i}."""
    key = os.environ.get('TOURAPI_KEY', '').strip()
    path = os.path.join(tmp, 'info.json')
    have = read_json(path) or {}
    need = [it for it in items.values() if it.get('src') == 'tour' and it.get('cid') and not (it.get('i') or {}).get('v') and it['cid'] not in have]
    if not key: return '정리 — TOURAPI_KEY 없음, 건너뜀(정리 없는 행사 %d건)' % len(need)
    need = need[:limit]
    with ThreadPoolExecutor(6) as ex: res = list(ex.map(lambda it: (it['cid'], tour_info(key, it['cid'], nowtxt)), need))
    ok = {c: i for c, i in res if i}
    have.update(ok)
    with open(path, 'w', encoding='utf-8') as f: json.dump(have, f, ensure_ascii=False)
    return '정리 — 새로 %d건 · 실패 %d건(다음 회차에 다시) · 출연 칸 있음 %d건' % (len(ok), len(need) - len(ok), sum(1 for i in ok.values() if i.get('cast')))

# ───────────────────────── 블록(주말·연휴) ─────────────────────────
def blocks(today):
    """오늘부터 조회 창 끝까지의 쉬는 날 묶음. [(start, end, holiday_name|''), ...]"""
    out = []; cur = None
    for i in range(0, WINDOW + 8):
        d = today + dt.timedelta(days=i); s = d.isoformat()
        off = d.weekday() >= 5 or s in HOLI
        if off:
            if cur is None: cur = [d, d, HOLI.get(s, '')]
            else: cur[1] = d; cur[2] = cur[2] or HOLI.get(s, '')
        elif cur is not None:
            out.append(tuple(cur)); cur = None
    if cur is not None: out.append(tuple(cur))
    return out

def box_plan(today):
    bl = blocks(today)
    b1 = next(b for b in bl if b[1] >= today)
    b2 = next((b for b in bl if b[0] > b1[1]), None)
    wend = today + dt.timedelta(days=WINDOW)
    r1 = (today, b1[1]); r2 = (b1[1] + dt.timedelta(days=1), b2[1]) if b2 else None
    r3 = ((r2[1] if r2 else r1[1]) + dt.timedelta(days=1), wend)
    def name(b, r, nth):
        nm = '🎊 %s 연휴' % b[2] if b[2] else ('🎪 이번 주말' if nth == 1 else '🎪 다음 주말')
        if r[0] < b[0]: nm += '까지'
        rng = md(r[0]) if r[0] == r[1] else '%s~%s' % (md(r[0]), md(r[1]))
        return '%s (%s)' % (nm, rng)
    n1 = name(b1, r1, 1); n2 = name(b2, r2, 2) if b2 else None
    hol3 = [b[2] for b in bl if b[2] and r3[0] <= b[0] <= r3[1]]
    n3 = '🗓 그 뒤%s (%s~%s)' % (' — %s 연휴 포함' % hol3[0] if hol3 else '', md(r3[0]), md(r3[1]))
    days1 = [b1[0] + dt.timedelta(days=i) for i in range((b1[1] - b1[0]).days + 1)]
    days2 = [b2[0] + dt.timedelta(days=i) for i in range((b2[1] - b2[0]).days + 1)] if b2 else []
    hb = [b for b in bl if b[2] and b[0] <= wend]
    notice = ''
    if hb:
        cnt = ['한', '두', '세', '네'][min(len(hb), 4) - 1]
        desc = ' · '.join('%s %s(%s)~%s(%s)' % (b[2], md(b[0]), WD[b[0].weekday()], md(b[1]), WD[b[1].weekday()]) if b[0] != b[1] else '%s %s(%s)' % (b[2], md(b[0]), WD[b[0].weekday()]) for b in hb)
        notice = '🗓 %d주 사이에 연휴가 %s 번%s — %s' % (WINDOW // 7, cnt, '입니다' if len(hb) > 1 else ' 있습니다', desc)
    return {'r1': r1, 'r2': r2, 'r3': r3, 'n1': n1, 'n2': n2, 'n3': n3, 'days1': days1, 'days2': days2, 'notice': notice}

# ───────────────────────── 날씨 ─────────────────────────
def sky(c, p):
    wet = 51 <= c <= 67 or 80 <= c <= 82
    if wet and p is not None and p < 30: return '☁️ 흐림'      # 강수확률 30% 미만 이슬비 코드는 모델 잡음
    if c == 0: return '☀️ 맑음'
    if c in (1, 2): return '🌤 구름 조금'
    if c == 3: return '☁️ 흐림'
    if c in (45, 48): return '🌫 안개'
    if 51 <= c <= 57: return '🌦 이슬비'
    if 71 <= c <= 77 or c in (85, 86): return '❄️ 눈'
    if 95 <= c <= 99: return '⛈ 뇌우'
    return '🌧 비'

def weather(tmp, today):
    w = read_json(os.path.join(tmp, 'w.json'))
    if not w: return None
    w = w.get('daily', w)
    out = {}
    try:
        for i, day in enumerate(w['time']):
            c, lo, hi, p = w['weather_code'][i], w['temperature_2m_min'][i], w['temperature_2m_max'][i], w['precipitation_probability_max'][i]
            if None in (c, lo, hi): continue
            D = dt.date.fromisoformat(day)
            s = '%s %s %s %d~%d°' % (WD[D.weekday()], md(D), sky(c, p), round(lo), round(hi))
            if p is not None and p >= 30: s += ' 💧%d%%' % p
            out[D] = s
    except Exception: return None
    return out

def wx_line(wx, days, today):
    if not wx: return ''
    parts = [wx[d] for d in days if d in wx]
    if not parts: return ''
    s = ' · '.join(parts)
    if any((d - today).days >= 8 for d in days if d in wx): s += ' (먼 예보라 바뀔 수 있음)'
    return s

# ───────────────────────── 원장 읽기 ─────────────────────────
def load_ledger(tmp, now):
    led = unwrap(read_json(os.path.join(tmp, 'led', 'feed', 'current.json')) or {})
    if not led or not isinstance(led.get('items'), list):
        return {'items': {}, 'skipped': {}, 'lastmail': '', 'note': '원장 없음 — 첫 실행, NEW 생략', 'fresh': True}
    prev = {}
    if led.get('v', 0) >= LEDGER_V:
        for it in led['items']: prev[it['k']] = it
        lastmail = led.get('lastmail', '')
        note = '원장 v%s · %s 기준 %d건' % (led.get('v'), led.get('generated', '?'), len(led['items']))
    else:  # v16 이전 feed 를 원장으로 승격 — first/seen 은 그 feed 시각으로
        g = led.get('generated', '')
        try: gdt = dt.datetime.strptime(g, '%Y-%m-%d %H:%M').replace(tzinfo=KST)
        except Exception: gdt = now
        lastmail = (gdt if is_regular(gdt) else last_regular_before(gdt)).strftime('%Y-%m-%d %H:%M')
        for it in led['items']:
            src = it.get('b') if it.get('b') in ('yeyak', 'culture') else 'tour'
            prev[it['k']] = dict(it, src=src, first=(g if it.get('new') else lastmail), seen=g, cid=it.get('cid', ''), s=it.get('s', ''), cat=it.get('cat', ''), kid=False)
        note = '원장 승격 — v16 feed %s (%d건) → v%d, 마지막 정기 발송을 %s 로 봄' % (g, len(led['items']), LEDGER_V, lastmail)
    skipped = {s['k']: s for s in led.get('skipped', []) if isinstance(s, dict) and s.get('k')}
    return {'items': prev, 'skipped': skipped, 'lastmail': lastmail, 'note': note, 'fresh': False}

def load_coll(tmp, name):
    """고르기 화면의 추가 표시 — visits(✓ 다녀옴: {t, d, ds:[날짜…]}) · go(🚗 간다: {t, e}). 없으면 빈 dict."""
    out = {}
    for p in glob.glob(os.path.join(tmp, name, name, '*.json')):
        d = unwrap(read_json(p) or {})
        if isinstance(d, dict): out[os.path.basename(p)[:-5]] = d
    return out

def load_marks(tmp, today):
    hide, pin, yr, expired = {}, {}, 0, 0
    for p in glob.glob(os.path.join(tmp, 'marks', 'marks', '*.json')):
        d = unwrap(read_json(p) or {})
        if not isinstance(d, dict): continue
        k = os.path.basename(p)[:-5]
        y = d.get('y') is True and d.get('s') == 'hide'; e = str(d.get('e') or '')
        if not y and e and e < today.isoformat(): expired += 1; continue
        if d.get('s') == 'hide': hide[k] = d; yr += y
        elif d.get('s') == 'pin': pin[k] = d
    return hide, pin, yr, expired

# ───────────────────────── 합치기 ─────────────────────────
def merge(tmp, now, today, prev, skipped, lastmail):
    nowtxt = now.strftime('%Y-%m-%d %H:%M')
    items, seen_k, dup, regions = {}, set(), 0, {}
    for l in lines(os.path.join(tmp, 'f.txt')):
        f = l.split('|')
        if len(f) < 9: continue
        rg, t, ad, s, e, x, y, cat, cid = [c.strip() for c in f[:9]]
        if not (re.fullmatch('[0-9]{8}', s) and re.fullmatch('[0-9]{8}', e)): continue
        regions[rg] = regions.get(rg, 0) + 1
        k = key(t)
        if k in seen_k: dup += 1; continue
        seen_k.add(k)
        try: kv = round(km(float(y), float(x)), 1) if x and y else None
        except ValueError: kv = None
        S, E = iso(s), iso(e)
        old = prev.get(k) or skipped.get(k)
        it = {'k': k, 'src': 'tour', 'cid': cid, 't': t, 'g': (ad.split() + ['', ''])[1] if ad else '', 'addr': ad,
              's': S.isoformat(), 'e': E.isoformat(), 'kmv': kv, 'cat': cat,
              'u': 'https://search.naver.com/search.naver?query=' + urllib.parse.quote_plus(t),
              'x': (old or {}).get('x', '') if old and old.get('src', 'tour') == 'tour' else '',
              'first': (old or {}).get('first') or nowtxt, 'seen': nowtxt, 'gone': False, 'kid': bool((old or {}).get('kid'))}
        if old and isinstance(old.get('i'), dict) and old['i'].get('v') and old.get('cid') == cid: it['i'] = old['i']   # 정리는 한 번만 부른다
        if not it['g']: it['g'] = it['addr'].split()[0] if it['addr'] else ''
        items[k] = it
    stat = {'kept': sum(1 for k in items if k in prev), 'added': sum(1 for k in items if k not in prev), 'gone': 0, 'ended': 0, 'dup': dup, 'regions': regions, 'total': len(items)}
    # 이전에만 있던 TourAPI 행사 — 끝나는 날 전이면 「목록에서 빠짐」으로 남긴다
    for k, old in prev.items():
        if k in items or old.get('src', 'tour') != 'tour': continue
        e = old.get('e') or ''
        if not e or e < today.isoformat(): stat['ended'] += 1; continue
        it = dict(old); it['gone'] = True; it['src'] = 'tour'
        if not it.get('s'):   # v16 feed 엔 시작일이 없다 — 날짜 칸에서 되살린다
            m = re.match(r'(\d+)/(\d+)~', it.get('d', ''))
            it['s'] = dt.date(today.year, int(m.group(1)), int(m.group(2))).isoformat() if m else (today - dt.timedelta(days=1)).isoformat()
        if it.get('kmv') is None:
            m = re.match(r'([\d.]+) km', it.get('km', '') or ''); it['kmv'] = float(m.group(1)) if m else None
        items[k] = it; stat['gone'] += 1
    return items, stat

def load_sk(tmp, now, prev, lastmail):
    sk = read_json(os.path.join(tmp, 'sk.json'))
    if isinstance(sk, str):
        try: sk = json.loads(sk)
        except Exception: sk = None
    if not sk: return None, [], {}
    nowtxt = now.strftime('%Y-%m-%d %H:%M'); out = []
    for box in ('yeyak', 'culture'):
        for x in sk.get(box, []):
            k = key(x['t']); old = prev.get(k)
            out.append({'k': k, 'src': box, 'b': box, 'cid': '', 't': x['t'], 'u': x['u'], 'g': x.get('g', ''), 'd': x.get('d', ''),
                        'km': '%.1f km' % x['k'] if isinstance(x.get('k'), (int, float)) else '', 'kmv': x.get('k'), 'x': x.get('x', ''), 'e': x.get('e', ''),
                        'soon': '⏳ %s 마감' % (x.get('d', '').split('~')[-1].strip()) if x.get('soon') and box == 'yeyak' else '',
                        'first': (old or {}).get('first') or nowtxt, 'seen': nowtxt, 'gone': False, 'kid': False, 'cat': '', 's': ''})
    cafe = [(re.sub(r'^서울형 키즈카페\s*|\(.*?\)', '', c['t']).strip(), c['u'], c['k']) for c in sk.get('kidscafe', [])]
    meta = {'generated': sk.get('generated_kst', ''), 'cafe': cafe, 'cafe_count': sk.get('kidscafe_count', 0),
            'note': {b: sk.get(b + '_note', '') for b in ('yeyak', 'culture')}}
    try:
        g = dt.datetime.strptime(meta['generated'], '%Y-%m-%d %H:%M').replace(tzinfo=KST); meta['age_h'] = (now - g).total_seconds() // 3600
    except Exception: meta['age_h'] = None
    return sk, out, meta

# ───────────────────────── 파생 칸(상자·날짜·배지) ─────────────────────────
def derive(items, plan, today, wx):
    for it in items.values():
        if it['src'] != 'tour': continue
        S, E = dt.date.fromisoformat(it['s']), dt.date.fromisoformat(it['e'])
        days = (E - S).days + 1
        it['km'] = '%.1f km' % it['kmv'] if it.get('kmv') is not None else ''
        if days > PERM_DAYS: it['b'] = 'b4'
        elif S <= plan['r1'][1]: it['b'] = 'b1'
        elif plan['r2'] and S <= plan['r2'][1]: it['b'] = 'b2'
        else: it['b'] = 'b3'
        if it['b'] == 'b4' and E >= dt.date(today.year, 12, 25): it['d'] = '연중'
        elif S <= today: it['d'] = '~' + md(E)
        elif S == E: it['d'] = md(S)
        else: it['d'] = '%s~%s' % (md(S), md(E))
        left = (E - today).days
        it['soon'] = ('⏳ 오늘(%s) 종료' % md(E) if left == 0 else '⏳ 내일(%s) 종료' % md(E) if left == 1 else '⏳ %s 종료' % md(E)) if S <= today and 0 <= left <= 7 else ''
        it['big'] = next((v for kk, v in BIG.items() if kk in n(it['t'])), '')

def badges(it, wet):
    b = []
    if it.get('big'): b.append(('big', it['big']))
    if '🧒' in (it.get('x') or '') or it.get('kid') or (it['src'] == 'tour' and KID_TITLE.search(it['t'])):
        if it['src'] == 'tour': b.append(('kid', '🧒 아이 동반'))
    if wet and INDOOR.search((it.get('x') or '') + ' ' + it['t']): b.append(('indoor', '🏠 실내'))
    if it.get('soon'): b.append(('soon', it['soon']))
    if it.get('gone'): b.append(('gone', '⚠ 목록에서 빠짐'))
    if it.get('vis'): b.append(('vis', it['vis']))
    return b

# ───────────────────────── HTML ─────────────────────────
SP = {
    'new': "<span style='background-color:#e8175d;color:#ffffff;font-weight:800;padding:1px 6px;border-radius:5px;font-size:11px;letter-spacing:.3px'>NEW</span>",
    'pin': "<span style='background-color:#fdf1dc;border:1px solid #f0d09a;color:#b45309;font-weight:700;padding:1px 6px;border-radius:5px;font-size:12px'>📌 고정</span>",
    'big': "<span style='background-color:#1e3a8a;color:#ffffff;font-weight:700;padding:1px 6px;border-radius:5px;font-size:12px'>%s</span>",
    'kid': "<span style='background-color:#fdf3e0;border:1px solid #f0d9a0;color:#8a5a00;padding:1px 6px;border-radius:5px;font-size:12px'>%s</span>",
    'soon': "<span style='background-color:#fde8e6;border:1px solid #f3c9c4;color:#c0392b;padding:1px 6px;border-radius:5px;font-size:12px'>%s</span>",
    'indoor': "<span style='background-color:#e7f0fb;border:1px solid #bcd3ef;color:#1e4fa3;padding:1px 6px;border-radius:5px;font-size:12px'>%s</span>",
    'gone': "<span style='background-color:#f3f4f6;border:1px solid #d1d5db;color:#6b7280;padding:1px 6px;border-radius:5px;font-size:12px'>%s</span>",
    'km': "<span style='color:#8a93a3;font-size:12px'>%s</span>",
    'vis': "<span style='background-color:#e8f5ec;border:1px solid #b9dfc4;color:#1f6b3a;padding:1px 6px;border-radius:5px;font-size:12px'>%s</span>",
    'go': "<span style='background-color:#1e3a8a;color:#ffffff;font-weight:800;padding:1px 6px;border-radius:5px;font-size:11px'>🚗 간다</span>",
}
COLORS = {'green': ('#cde3cd', '#f4faf4', '#2e7d4f'), 'orange': ('#f5d0b5', '#fff6ef', '#b4541a'), 'purple': ('#ddd3f1', '#f7f4fd', '#5b3fa0'),
          'gray': ('#e2e6ec', '#f6f7f9', '#4b5563'), 'teal': ('#bfe3dc', '#f1faf8', '#0f766e'), 'blue': ('#c9d8f2', '#f3f7fd', '#1e4fa3')}

def info_link(it):
    """📋 정리 — 메일엔 펼침을 못 넣어서(Gmail 이 지움) 고르기 화면의 그 행사로 가는 링크. ?k= 와 #k= 둘 다 — 화면이 어느 쪽이든 받으면 그 행사를 펼친다."""
    if not (it.get('i') or {}).get('v') or (it.get('i') or {}).get('none'): return ''
    return " <a href='%s?k=%s#k=%s' style='display:inline-block;border:1px solid #12409e;background-color:#eef4fd;color:#12409e;font-size:11.5px;font-weight:800;padding:0 7px;border-radius:5px;text-decoration:none;white-space:nowrap'>📋 정리 ↗</a>" % (ART, it['k'], it['k'])

def cast_line(it, pad='0 0 5px 11px'):
    """🎤 출연 — 관광공사 「출연」 칸이 있는 행사만(드물다). 누가 나오는지는 메일에서도 바로 보이게."""
    c = ((it.get('i') or {}).get('cast') or '').replace('\n', ' ')
    if not c: return ''
    return "\n<div style='font-size:12px;color:#374151;line-height:1.5;padding:%s'>🎤 <b>%s</b></div>" % (pad, esc(cut(c, 90)))

def row_html(it, isnew, pinned, wet, detail):
    parts = ['· ']
    if pinned: parts.append(SP['pin'] + ' ')
    if isnew: parts.append(SP['new'] + ' ')
    parts.append("<a href='%s' style='color:#12409e;font-weight:700;text-decoration:underline'>%s</a>" % (esc(it['u']), esc(it['t'])))
    tail = ' — ' + esc(it.get('g', '')) + ' · ' + esc(it['d'])
    if it.get('km'): tail += ' ' + SP['km'] % esc(it['km'])
    for kind, txt in badges(it, wet): tail += ' ' + SP[kind] % esc(txt)
    parts.append(tail + info_link(it) + '<br>')
    parts.append(cast_line(it))
    if detail and it.get('x'):
        parts.append("\n<div style='font-size:12px;color:#8a93a3;line-height:1.5;padding:0 0 5px 11px'>%s</div>" % esc(it['x']))
    return ''.join(parts)

def box_html(color, title, sub, rows, empty_text, extra=''):
    bd, bg, tc = COLORS[color]
    h = ["<div style='margin:18px 14px 0;padding:12px 14px 8px;border-radius:12px;border:1px solid %s;background-color:%s'>" % (bd, bg),
         "<div style='font-size:13px;font-weight:800;color:%s'>%s</div>" % (tc, esc(title))]
    if sub: h.append(sub)
    if rows: h.append("<div style='margin-top:8px;font-size:13px;line-height:1.95;color:#374151'>\n" + '\n'.join(rows) + '\n</div>')
    else: h.append("<div style='margin-top:8px;font-size:13px;color:#6b7280'>%s</div>" % esc(empty_text))
    if extra: h.append(extra)
    h.append('</div>')
    return '\n'.join(h)

def sort_box(lst, pin):
    return sorted(lst, key=lambda it: (0 if it['k'] in pin else 1, it.get('kmv') if it.get('kmv') is not None else 9999))

# ───────────────────────── 실행 ─────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('mode', choices=['plan', 'mail'])
    ap.add_argument('--tmp', default='/tmp')
    ap.add_argument('--make', default='', help='정비 ⑩ Make 사용량 글자 (예: 412/1000회 · 10/9 초기화)')
    ap.add_argument('--note', action='append', default=[], help='정비에 덧붙일 줄(재시도·실패 등)')
    ap.add_argument('--now', default='', help='시험용 KST 시각 YYYY-MM-DD HH:MM')
    a = ap.parse_args()
    tmp = a.tmp
    now = dt.datetime.strptime(a.now, '%Y-%m-%d %H:%M').replace(tzinfo=KST) if a.now else dt.datetime.now(KST)
    today = now.date(); nowtxt = now.strftime('%Y-%m-%d %H:%M')
    regular = is_regular(now)
    months = suwan_months(today)
    P = lambda *x: print(*x)

    led = load_ledger(tmp, now)
    prev, skipped, lastmail = led['items'], led['skipped'], led['lastmail']
    hide, pin, yr, expired = load_marks(tmp, today)
    items, stat = merge(tmp, now, today, prev, skipped, lastmail)
    sk, skitems, skmeta = load_sk(tmp, now, prev, lastmail)
    plan = box_plan(today)
    wx = weather(tmp, today)
    derive(items, plan, today, wx)
    fails = [l.split('|', 1) for l in lines(os.path.join(tmp, 'fail.txt'))]

    P('시각 %s (%s) · %s · 수완 만 %d세 %d개월 · 조회 창 %s~%s' % (nowtxt, WD[now.weekday()], '정기 회차' if regular else '수동 시험(받는 사람 wsc627 만)', months // 12, months % 12, md(today), md(today + dt.timedelta(days=WINDOW))))
    P('원장:', led['note'], '· 마지막 정기 발송', lastmail or '(없음)')
    P('표시: 숨김 %d(매년 %d) · 고정 %d · 끝나서 풀린 것 %d' % (len(hide), yr, len(pin), expired))
    P('수집: %s → 받은 %d건(중복 %d 제외) · 이어짐 %d · 새로 %d · 목록에서 빠졌지만 남김 %d · 끝나서 지움 %d' % (' · '.join('%s %d' % kv for kv in stat['regions'].items()), stat['total'], stat['dup'], stat['kept'], stat['added'], stat['gone'], stat['ended']))
    P('상자: ①', plan['n1'], '②', plan['n2'], '③', plan['n3'])
    if sk is None: P('⚠ sk.json 없음 — 🎟·🎭 상자는 안내 한 줄')
    if wx is None: P('⚠ w.json 없음 — 날씨 줄 생략')

    # ── 상세: d.txt 반영, 조회 필요 목록 ──
    dmap = {}
    for l in lines(os.path.join(tmp, 'd.txt')):
        f = (l.split('|') + [''] * 5)[:5]
        if f[0].strip(): dmap[f[0].strip()] = [c.strip() for c in f[1:]]
    fetched = 0
    for it in items.values():
        if it['src'] == 'tour' and it.get('cid') in dmap:
            fee, tm, pl, kid = dmap[it['cid']]
            segs = []
            for s in (fee, tm, pl, ('🧒 ' + kid) if kid else ''):
                if s and s not in segs: segs.append(s)
            it['x'] = ' · '.join(segs); fetched += 1
            if kid: it['kid'] = True
    need = [it for it in items.values() if it['src'] == 'tour' and it['b'] in ('b1', 'b2') and not it.get('x') and it['k'] not in hide and it['k'] not in skipped]
    reused = sum(1 for it in items.values() if it['src'] == 'tour' and it['b'] in ('b1', 'b2') and it.get('x') and it.get('cid') not in dmap)

    if a.mode == 'plan':
        P('\n[조회 필요 — ①② 상자에서 상세 줄이 없는 것 %d건. contentid 로 detailIntro2 를 하나씩 불러 d.txt 에 「cid|요금|시간|장소|아이 거리」]' % len(need))
        for it in sort_box(need, pin): P('조회|%s|%s|%s|%s' % (it['cid'], it['t'], it['b'], it['d']))
        newt = [it for it in items.values() if it['src'] == 'tour' and it['first'] == nowtxt]
        P('\n[새로 들어온 행사 %d건 — 제목만 보고 (a) 타지역 홍보 장터면 excl.txt 에 「cid|타지역 홍보」 (b) 지역 마스코트·캐릭터처럼 제목 낱말 규칙에 안 걸리는 아이 행사면 kid.txt 에 cid]' % len(newt))
        for it in sorted(newt, key=lambda z: z.get('kmv') or 9999): P('새|%s|%s|%s|%s' % (it['cid'], it['t'], it['b'], it.get('g', '')))
        gone = [it for it in items.values() if it.get('gone')]
        if gone: P('\n[목록에서 빠졌지만 남긴 것] ' + ' · '.join('%s(~%s)' % (it['t'], it['e'][5:].replace('-', '/')) for it in gone))
        P('\n[' + fetch_infos(tmp, items, nowtxt) + ']')
        json.dump({'now': nowtxt}, open(os.path.join(tmp, 'plan.json'), 'w'))
        return

    # ── mail: 제외·🧒 반영 ──
    for l in lines(os.path.join(tmp, 'excl.txt')):
        cid, why = (l.split('|', 1) + [''])[:2]
        it = next((x for x in items.values() if x.get('cid') == cid.strip()), None)
        if it: skipped[it['k']] = {'k': it['k'], 'cid': cid.strip(), 't': it['t'], 'src': 'tour', 'e': it['e'], 'why': why.strip() or '제외', 'at': nowtxt}
    for l in lines(os.path.join(tmp, 'kid.txt')):
        it = next((x for x in items.values() if x.get('cid') == l.strip()), None)
        if it: it['kid'] = True
    skipped = {k: v for k, v in skipped.items() if (v.get('e') or '9') >= today.isoformat()}   # 끝난 제외는 잊는다

    infos = read_json(os.path.join(tmp, 'info.json')) or {}
    for it in items.values():
        if it.get('cid') in infos and not (it.get('i') or {}).get('v'): it['i'] = infos[it['cid']]
    allitems = list(items.values()) + skitems
    for it in allitems: it['new'] = bool(lastmail) and it['first'] > lastmail and not led['fresh']
    # ✓ 다녀옴 · 🚗 간다 (2026-10-04 추가) — 다녀온 날이 이번 행사 시작 전이면 「예전에 갔던 곳」(제목 키가 연도를 떼서 내년 같은 축제에 붙는다)
    visits, gos = load_coll(tmp, 'visits'), load_coll(tmp, 'go')
    for it in allitems:
        v = visits.get(it['k'])
        if not v: continue
        ds = sorted(x for x in (v.get('ds') or [v.get('d', '')]) if re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(x)))
        if not ds: continue
        start = it.get('s') or ''
        now_ds = [x for x in ds if not start or x >= start]
        if now_ds: it['vis'] = '✓ %s 다녀옴' % md(dt.date.fromisoformat(now_ds[-1]))
        else:
            last = dt.date.fromisoformat(ds[-1])
            it['vis'] = '🔁 %s 갔던 곳' % ('작년에' if last.year == today.year - 1 else '%d년에' % last.year if last.year < today.year else '%s에' % md(last))
    go_k = {k for k, v in gos.items() if (str(v.get('e') or '9') >= today.isoformat())}
    go_items = [it for it in allitems if it['k'] in go_k and it['k'] not in skipped and not (it.get('vis') or '').startswith('✓')]
    go_set = {it['k'] for it in go_items}
    shown = [it for it in allitems if it['k'] not in hide and it['k'] not in skipped]
    body = [it for it in shown if it['src'] == 'tour' and it['b'] != 'b4']; perm = [it for it in shown if it['b'] == 'b4']
    hidden_n = sum(1 for it in items.values() if it['k'] in hide); skip_n = sum(1 for it in items.values() if it['k'] in skipped)
    assert stat['total'] + stat['gone'] == len(body) + len(perm) + hidden_n + skip_n, (stat, len(body), len(perm), hidden_n, skip_n)
    newK = sum(1 for it in body + perm if it['new']); newS = sum(1 for it in shown if it['src'] != 'tour' and it['new'])
    cats = {c: sum(1 for it in body if it.get('cat') == c) for c in CAT}
    by = {b: sort_box([it for it in shown if it['b'] == b and it['k'] not in go_set], pin) for b in ('b1', 'b2', 'b3', 'b4', 'yeyak', 'culture')}
    wl1, wl2 = wx_line(wx, plan['days1'], today), wx_line(wx, plan['days2'], today)
    wet1, wet2 = any(w in wl1 for w in WET), any(w in wl2 for w in WET)
    hold = ' · '.join(f[0] for f in fails)

    # ── 상자 ──
    def wxdiv(s): return "<div style='font-size:12px;color:#374151;margin-top:4px'>%s</div>" % esc(s) if s else ''
    boxes_meta = []
    nhid = {b: sum(1 for it in allitems if it['b'] == b and it['k'] in hide) for b in ('b1', 'b2', 'b3', 'b4', 'yeyak', 'culture')}
    def bx(bid, color, name, sub, lst, empty, wet, detail, extra=''):
        title = '%s — %d건' % (name, len(lst)) if bid.startswith('b') else name
        boxes_meta.append({'id': bid, 'name': title, 'color': color})
        if not lst and nhid.get(bid): empty = '이 상자의 %d건은 모두 고르기에서 숨겼습니다 — 되살리려면 📋 고르기의 「✕ 숨김」 탭' % nhid[bid]
        return box_html(color, title, sub, [row_html(it, it['new'], it['k'] in pin, wet, detail) for it in lst], empty, extra)
    # 🚗 이번에 갈 곳 — 고르기에서 「간다」를 누른 행사만, 원래 상자에서 빼서 맨 위에 크게(중복 없음)
    HG = ''
    if go_items:
        cards = []
        for it in sorted(go_items, key=lambda z: (z.get('s') or '', z.get('kmv') or 9999)):
            s0 = dt.date.fromisoformat(it['s']) if re.fullmatch(r'\d{4}-\d{2}-\d{2}', it.get('s') or '') else today
            e0 = dt.date.fromisoformat(it['e']) if re.fullmatch(r'\d{4}-\d{2}-\d{2}', it.get('e') or '') else today + dt.timedelta(days=13)
            lo, hi = max(s0, today), min(e0, today + dt.timedelta(days=13))
            span = [lo + dt.timedelta(days=i) for i in range(max(0, (hi - lo).days + 1))]
            offd = [d for d in span if d.weekday() >= 5 or d.isoformat() in HOLI] or span
            wl = wx_line(wx, offd[:3], today)
            meta = ' · '.join(x for x in (it.get('g', ''), it.get('d', ''), it.get('km', '')) if x)
            bs = ' '.join(SP[k] % esc(t) for k, t in badges(it, any(w in wl for w in WET)))
            c = ["<div style='padding:9px 0 7px;border-top:1px solid #dbe5f5'>",
                 "<div style='font-size:15px;font-weight:800;line-height:1.5'>%s <a href='%s' style='color:#12409e;text-decoration:underline'>%s</a></div>" % (SP['go'], esc(it['u']), esc(it['t'])),
                 "<div style='font-size:12.5px;color:#374151;margin-top:3px'>%s %s%s</div>" % (esc(meta), bs, info_link(it))]
            cl = cast_line(it, '3px 0 0')
            if cl: c.append(cl)
            if it.get('x'): c.append("<div style='font-size:12.5px;color:#4b5563;margin-top:3px;line-height:1.55'>%s</div>" % esc(it['x']))
            if wl: c.append("<div style='font-size:12px;color:#1e3a8a;margin-top:3px'>%s</div>" % esc(wl))
            c.append('</div>')
            cards.append('\n'.join(c))
        HG = ("<div style='margin:18px 14px 0;padding:12px 14px 6px;border-radius:12px;border:2px solid #93b4e8;background-color:#eef4fd'>"
              "<div style='font-size:13px;font-weight:800;color:#1e3a8a'>🚗 이번에 갈 곳 — %d건</div>"
              "<div style='font-size:12px;color:#6b7280;margin-top:3px'>고르기에서 「🚗 간다」를 누른 행사입니다. 다녀오면 「✓ 다녀옴」을 눌러 주세요.</div>\n%s\n</div>") % (len(go_items), '\n'.join(cards))
    H1 = bx('b1', 'green', plan['n1'], wxdiv(wl1), by['b1'], '이 기간에 시작하는 행사 없음', wet1, True)
    H2 = bx('b2', 'orange', plan['n2'] or '🎪 다음 주말', wxdiv(wl2), by['b2'], '이 기간에 시작하는 행사 없음', wet2, True) if plan['n2'] else ''
    if sk is None:
        Y = box_html('teal', '🎟 신청 받는 중 — 서울 아이·가족 프로그램', '', [], '서울 목록을 받지 못했습니다'); C = box_html('blue', '🎭 서울 공연·체험 — 아이와 갈 만한 것', '', [], '서울 목록을 받지 못했습니다')
        boxes_meta += [{'id': 'yeyak', 'name': '🎟 신청 받는 중 — 서울 아이·가족 프로그램', 'color': 'teal'}, {'id': 'culture', 'name': '🎭 서울 공연·체험 — 아이와 갈 만한 것', 'color': 'blue'}]
    else:
        cafe = ''
        if skmeta['cafe']:
            cafe = "<div style='font-size:12px;color:#374151;line-height:1.7;padding:6px 0 2px'>🎠 서울형 키즈카페 예약 — " + ' · '.join("<a href='%s' style='color:#12409e;text-decoration:underline'>%s</a> <span style='color:#8a93a3'>%.1f km</span>" % (esc(u), esc(t), k) for t, u, k in skmeta['cafe']) + " <span style='color:#8a93a3'>(서울 %d곳)</span></div>" % skmeta['cafe_count']
        Y = bx('yeyak', 'teal', '🎟 신청 받는 중 — 서울 아이·가족 프로그램 %d건' % len(by['yeyak']), "<div style='font-size:12px;color:#6b7280;line-height:1.6;margin-top:4px'>서울시 공공서비스예약에서 골랐습니다. 대부분 무료·선착순이라 <b>접수 마감 전에 신청해야 갈 수 있는 것</b>들입니다. 날짜 칸은 접수 마감일입니다.</div>", by['yeyak'], '지금 접수 중인 것 없음', wet1, True, cafe)
        C = bx('culture', 'blue', '🎭 서울 공연·체험 — 아이와 갈 만한 것 %d건' % len(by['culture']), "<div style='font-size:12px;color:#6b7280;line-height:1.6;margin-top:4px'>서울 문화포털에서 앞으로 45일 안에 볼 수 있는 아이·가족 행사를 골랐습니다.</div>", by['culture'], '45일 안에 새로 볼 것 없음', wet1, True)
    H3 = bx('b3', 'purple', plan['n3'], '', by['b3'], '이 기간에 시작하는 행사 없음', False, False)
    H4 = bx('b4', 'gray', '🔁 상설 프로그램', "<div style='font-size:12px;color:#6b7280;line-height:1.6;margin-top:4px'>60일 넘게 이어지는 것들이라 위 구역에서는 뺐습니다. <b>날짜에 쫓기지 않으니 아무 때나 갈 수 있는 목록</b>입니다.</div>", by['b4'], '해당 없음', False, False)

    # ── 정비 ──
    rep = ['출처 한국관광공사 TourAPI searchFestival2 · 조회 창 %s~%s · 조회 시각 KST %s · EFFORT %s · 조립 build.py v%d' % (md(today), md(today + dt.timedelta(days=WINDOW)), nowtxt, os.environ.get('CLAUDE_CODE_EFFORT_LEVEL', '모델기본'), LEDGER_V)]
    rep.append('검산: %s → 받은 %d건%s + 목록에서 빠졌지만 남긴 %d건 = 본문 %d + 상설 %d + 고르기 숨김 %d + 제외 %d' % (' · '.join('%s %d' % kv for kv in stat['regions'].items()), stat['total'], '(중복 %d 제외)' % stat['dup'] if stat['dup'] else '', stat['gone'], len(body), len(perm), hidden_n, skip_n))
    rep.append('NEW 기준: 마지막 정기 발송 %s 이후 원장에 처음 들어온 것 · NEW %d건 (🎟·🎭 %d건 별도)%s' % (lastmail or '없음', newK, newS, ' · 원장 없음이라 NEW 생략' if led['fresh'] else ''))
    ex = [v for v in skipped.values()]
    rep.append('제외한 것: ' + (' · '.join('%s(%s)' % (v['t'], v['why']) for v in ex) if ex else '없음'))
    rep.append('거리 기준점 스타필드 시티 위례 · 직선거리라 도로 거리보다 짧습니다')
    rep.append('날씨 %s · 상세 재사용 %d건 · 새로 조회 %d건 · 상세 형식 v11' % ('출처 Open-Meteo 예보 · 스타필드 좌표' if wx else '조회 실패(줄 생략)', reused, fetched))
    gone = [it for it in items.values() if it.get('gone')]
    if gone: rep.append('관광공사 목록에서 내려갔지만 끝나는 날 전이라 남김 %d건 — %s (취소면 고르기에서 ✕)' % (len(gone), ' · '.join(it['t'] for it in gone)))
    if today.isoformat() >= HOLI_UNTIL: rep.append('⚠️ 공휴일 표 갱신 필요 (2027년분 없음)')
    if today.isoformat() >= BIG_UNTIL: rep.append('⚠️ 대표축제 표 확인 필요 (2027 글로벌축제 · 2028~2029 문화관광축제 재지정)')
    if fails: rep.append('⚠️ 수집 실패 — ' + ' · '.join('%s(%s)' % (f[0], f[1] if len(f) > 1 else '') for f in fails))
    if sk is None: rep.append('서울 아이 거리 — 목록을 받지 못함')
    else:
        rep.append('서울 아이 거리 — 목록 %s 갱신 · 🎟 %d건(NEW %d) · 🎭 %d건(NEW %d) · 키즈카페 %d곳' % (skmeta['generated'][5:].replace('-', '/'), len(by['yeyak']), sum(1 for i in by['yeyak'] if i['new']), len(by['culture']), sum(1 for i in by['culture'] if i['new']), skmeta['cafe_count']))
        if skmeta['age_h'] is not None and skmeta['age_h'] > 48: rep.append('⚠️ 서울 거름망 갱신 멈춤(마지막 %s) — GitHub Actions 확인' % skmeta['generated'])
    rep.append('고르기 — 숨김 %d건(매년 %d) · 고정 %d건 · 끝나서 풀린 것 %d건 · 🚗 간다 %d건 · ✓ 다녀옴 기록 %d곳 · %s' % (len(hide), yr, len(pin), expired, len(go_items), len(visits), led['note']))
    rep.append(('Make 이번 달 ' + a.make) if a.make else 'Make 사용량 미확인')
    if not regular: rep.append('수동 시험이라 네이버 주소 제외 (%s %s 실행 — 예정 시각 밖)' % (WD[now.weekday()], now.strftime('%H:%M')))
    rep += a.note

    # ── 조립 ──
    N = len(body); K = newK
    # 맨 위 띠 — 이 메일이 어느 시점의 아티팩트(원장)를 찍은 것인지 + 고르기 링크 (2026-10-01 사용자 요청 「아티팩트(261001) 참고 제작 메일」)
    # 2026-10-10 사용자 「이 부분 화면을 더 넓게 쓰고 눈에 띄게」 — 얇은 한 줄 띠에서 남색 바탕 + 폭 전체 흰 버튼으로
    stamp = ("<div style='background-color:#1e3a8a;border-radius:14px 14px 0 0;padding:16px 18px 14px'>"
             "<div style='font-size:12px;color:#c7d7f5;font-weight:700;letter-spacing:.2px'>📋 아티팩트(%s) 참고 제작 메일</div>"
             "<div style='font-size:16px;font-weight:800;color:#ffffff;margin-top:4px;line-height:1.45'>행사마다 장소·시간·출연·요금을 정리해 두었습니다</div>"
             "<a href='%s' style='display:block;margin-top:11px;background-color:#ffffff;color:#1e3a8a;font-size:15px;font-weight:800;text-align:center;padding:12px 10px;border-radius:10px;text-decoration:none'>📋 고르기 열기 →</a>"
             "<div style='font-size:12px;color:#c7d7f5;margin-top:9px;line-height:1.6'>행사 줄의 <b style='color:#ffffff'>📋 정리 ↗</b>를 누르면 그 행사가 펼쳐진 채로 열립니다 · 📌 고정 · ✕ 숨기기 · 🚗 간다는 다음 메일부터 반영</div>"
             "</div>") % (now.strftime('%y%m%d'), ART)
    head = ["<div style='background-color:#eef0f4;padding:14px 8px;font-family:-apple-system,Segoe UI,Roboto,Apple SD Gothic Neo,sans-serif'>",
            "<div style='max-width:560px;margin:0 auto;background-color:#ffffff;border-radius:14px;color:#1f2937;padding-bottom:6px'>",
            stamp,
            "<div style='padding:12px 18px 4px'>",
            "<div style='font-size:11px;color:#8a93a3;font-weight:700;letter-spacing:.3px'>수도권 축제·행사 알림</div>",
            "<div style='font-size:23px;font-weight:800;color:#111827;margin-top:2px'>%d월 %d일 (%s)</div>" % (today.month, today.day, WD[today.weekday()]),
            "<div style='font-size:13px;color:#5b6472;margin-top:5px;line-height:1.5'>서울·경기·인천 <b>%d건</b> — 축제 %d · 공연 %d · 전시 %d · NEW %d건. 상설 프로그램 <b>%d건은 맨 아래</b>에 따로 실었습니다.%s</div>" % (N, cats['EV01'], cats['EV02'], cats['EV03'], K, len(perm), ' <b style=\'color:#c0392b\'>⚠️ %s 수집 실패 — 그 지역은 빠졌습니다.</b>' % esc(hold) if fails else ''),
            "<div style='font-size:12px;color:#6b7280;margin-top:9px;line-height:1.9'><span style='background-color:#fde8e6;border:1px solid #f3c9c4;color:#c0392b;padding:1px 6px;border-radius:5px;font-size:12px'>⏳ 곧 끝남</span> : 진행 중인데 7일 안에 끝남<br>거리는 위례 스타필드에서 직선거리<br>가까운 순으로 정렬</div>",
            "</div>"]
    if plan['notice']: head.append("<div style='background-color:#eaf3ff;border:1px solid #b9d4f5;border-radius:10px;margin:12px 18px 0;padding:11px 13px;font-size:13px;color:#1a4fc4;line-height:1.6'>%s</div>" % esc(plan['notice']))
    more = ["<div style='padding:26px 18px 2px;font-size:13px;font-weight:800'>🔎 더 찾아보기</div>",
            "<div style='margin:4px 18px 0;padding:0 4px;font-size:12px;color:#6b7280;line-height:1.6'>TourAPI에 안 잡히는 갈래는 여기서 봅니다. <b>탭처럼 생겼지만 각각 밖으로 나가는 링크</b>입니다.</div>",
            "<table cellpadding='0' cellspacing='0' style='border-collapse:collapse;margin:10px 18px 0'><tr>",
            "<td style='background-color:#1a56db;border-radius:9px 0 0 9px;padding:10px 15px'><a href='https://search.naver.com/search.naver?query=%ec%88%98%eb%8f%84%ea%b6%8c+%ec%b6%95%ec%a0%9c+%ec%9d%bc%ec%a0%95' style='color:#ffffff;font-weight:700;font-size:13px;text-decoration:none'>🎪 축제</a></td>",
            "<td style='background-color:#e8edf5;padding:10px 15px'><a href='https://tickets.interpark.com' style='color:#12409e;font-weight:700;font-size:13px;text-decoration:none'>🎵 공연·티켓</a></td>",
            "<td style='background-color:#e8edf5;border-radius:0 9px 9px 0;padding:10px 15px'><a href='https://search.naver.com/search.naver?query=%ec%84%9c%ec%9a%b8+%ec%a0%84%ec%8b%9c%ed%9a%8c+%ec%b6%94%ec%b2%9c' style='color:#12409e;font-weight:700;font-size:13px;text-decoration:none'>🖼 전시</a></td>",
            "</tr></table>",
            "<div style='padding:26px 18px 2px;font-size:13px;font-weight:800'>🔧 정비</div>",
            "<div style='margin:8px 18px 16px;padding:0 4px;font-size:12px;line-height:1.8;color:#6b7280'>" + '<br>'.join(' · ' + esc(r) for r in rep) + "</div>",
            "<div style='padding:10px 18px 20px;font-size:11px;color:#a8afba;border-top:1px solid #eee;margin-top:6px;line-height:1.6'>매주 수·금 17:00 자동 발송 · 출처 한국관광공사 TourAPI · 서울 열린데이터광장<br>행사 제목은 네이버 검색으로, 🎟·🎭 제목은 서울시 신청·안내 페이지로 연결됩니다</div>",
            "</div></div>"]
    htmlout = '\n'.join(head + [HG, H1, H2, Y, C, H3, H4] + more)
    subject = '%s[축제알림] %s(%s) 수도권 %d건 — %s · %s %d건' % ('⚠️ ' if fails else '', md(today), WD[today.weekday()], N, '🆕 %d건' % K if K else '🆕 없음', plan['n1'].split(' (')[0], len(by['b1']))
    to = ['wsc627@gmail.com'] + (['tjsdk3799@naver.com'] if regular else [])

    # ── 원장(feed/current) ──
    keep = ('k', 'b', 't', 'u', 'g', 'd', 'km', 'x', 'new', 'e', 'src', 'cid', 's', 'cat', 'big', 'kmv', 'first', 'seen', 'gone', 'kid', 'soon', 'i')
    order = {b: i for i, b in enumerate(('b1', 'b2', 'yeyak', 'culture', 'b3', 'b4'))}
    feed_items = [{k: it.get(k, '') for k in keep} for it in sorted([it for it in allitems if it['k'] not in skipped], key=lambda it: (order.get(it['b'], 9), 0 if it['k'] in pin else 1, it.get('kmv') if it.get('kmv') is not None else 9999))]
    for it in feed_items:
        if not it['i']: del it['i']
    for it in feed_items: it['kmv'] = it['kmv'] if isinstance(it['kmv'], (int, float)) else None; it['gone'] = bool(it['gone']); it['kid'] = bool(it['kid']); it['new'] = bool(it['new'])
    feed = {'v': LEDGER_V, 'generated': nowtxt, 'mail': '%s(%s) %s' % (md(today), WD[now.weekday()], now.strftime('%H:%M')), 'lastmail': lastmail if not led['fresh'] else nowtxt,
            'boxes': [b for b in boxes_meta if b['id'] in order], 'items': feed_items, 'skipped': list(skipped.values())}
    feed['boxes'].sort(key=lambda b: order[b['id']])
    with open(os.path.join(tmp, 'feed_art.json'), 'w', encoding='utf-8') as f: json.dump(feed, f, ensure_ascii=False)
    with open(os.path.join(tmp, 'mail.html'), 'w', encoding='utf-8') as f: f.write(htmlout)
    with open(os.path.join(tmp, 'subject.txt'), 'w', encoding='utf-8') as f: f.write(subject)
    with open(os.path.join(tmp, 'to.json'), 'w', encoding='utf-8') as f: json.dump(to, f)
    with open(os.path.join(tmp, 'report.txt'), 'w', encoding='utf-8') as f: f.write('\n'.join(rep))
    P('\n제목:', subject)
    P('받는 사람:', ', '.join(to))
    P('본문 %d + 상설 %d · NEW %d · 숨김 %d · 제외 %d · 목록에서 빠짐 %d · HTML %dKB · 원장 %d건 %dKB' % (len(body), len(perm), K, hidden_n, skip_n, len(gone), len(htmlout.encode()) // 1024, len(feed_items), len(json.dumps(feed, ensure_ascii=False).encode()) // 1024))
    for r in rep: P(' ·', r)
    P('\n다음: ① ArtifactData set feed/current ← %s/feed_art.json  ② send_message(to=%s, subject, htmlBody=%s/mail.html 내용)  ③ %s' % (tmp, json.dumps(to), tmp, ('정기 회차이므로 보낸 뒤 ArtifactData update feed/current data={"lastmail":"%s"}' % nowtxt) if regular else '수동 시험이라 lastmail 은 건드리지 않는다'))

if __name__ == '__main__':
    main()
