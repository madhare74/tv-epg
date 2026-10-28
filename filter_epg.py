#!/usr/bin/env python3
"""Скачивает XMLTV-файлы, оставляет только каналы из list.md и недавние передачи.
Для каждого канала берётся ОДИН источник (сначала b, затем a) и ОДИН вариант канала,
чтобы в итоговом файле не было дублей одной передачи с разным временем.
Результат: epg_small.xml.gz. Запуск: python filter_epg.py [a=путь b=путь]  (пути — для проверки без сети)

Источник mireamor/my_epg убран: с 27.10.2026 у него время на многих каналах сдвинуто на 2 часа
(например, «Родня» на «Мосфильме» 28.10 стоит в 18:20 вместо 20:20 МСК)."""
import gzip, re, sys, os, time, datetime as dt, urllib.request, shutil
from xml.etree.ElementTree import iterparse
from xml.sax.saxutils import escape, quoteattr

# Порядок важен: канал берётся из первого источника, где по нему есть передачи.
SOURCES = {"b": "https://raw.githubusercontent.com/Lorax121/epg_v2/main/data/epg2.xml.gz",      # EPG.ONE
           "a": "https://raw.githubusercontent.com/Lorax121/epg_v2/main/data/EPG_LITE.xml.gz"}  # iptvx.one
OUT = "epg_small.xml.gz"
ALIAS = {"5канал": "пятыйканал", "твц": "твцентр", "россиякультура": "россияк", "ru-tv": "rutv"}
SUFFIX = r"(\s+(fhd|uhd|hd|4k|orig|50))+$"
def canon(s):
    k = re.sub(r"[\s.!\-–—]", "", (s or "").lower().replace("ё", "е")); return ALIAS.get(k, k)

# Настройка «Время»: какие часы показывать в сводке.
#   московское      — цифры московского эфира (Кинопоиск отдаёт региональную версию канала,
#                     поэтому передача идёт в эти часы по местным часам). По умолчанию.
#   екатеринбургское — настоящее время по Екатеринбургу для московского эфира.
# Задаётся в list.md строкой «- Время: московское» в разделе «## Настройки».
TIME_MODE = "московское"
MSK = dt.timezone(dt.timedelta(hours=3))
LOCAL = dt.timezone(dt.timedelta(hours=5))   # часовой пояс, в который переводит сервер

channels, section = [], None
for line in open("list.md", encoding="utf-8"):
    s = line.strip()
    if s.startswith("#"):
        h = s.lstrip("#").strip().lower()
        section = "set" if h.startswith("настройк") else ("ch" if h.startswith("канал") else section)
        continue
    m = re.match(r"^[-*•]\s+(.+)$", s)
    if not m: continue
    item = re.sub(r"\\(.)", r"\1", m.group(1)).strip()
    st = re.match(r"(?i)^время\s*:\s*(\S+)", item)
    if st:
        TIME_MODE = "екатеринбургское" if st.group(1).lower().replace("ё", "е").startswith("екат") else "московское"
    elif section != "set":
        channels.append(item)
print("время в сводке:", TIME_MODE)

def fix_time(v):
    """Для «московского» режима: цифры московского времени с поясом +0500,
    чтобы сервер (переводящий в UTC+5) показал ровно московские часы."""
    if TIME_MODE != "московское": return v
    t = dt.datetime.strptime(v, "%Y%m%d%H%M%S %z").astimezone(MSK).replace(tzinfo=LOCAL)
    return t.strftime("%Y%m%d%H%M%S %z")
plus = {canon(c) for c in channels}
nice = {canon(c): c for c in channels}   # имя канала для сообщений — как в list.md
def base_channel(name):
    n = (name or "").lower()
    if re.search(r"[+-]\d|\(|\[|international|\bint\b|\bkz\b|\bkg\b|европа", n): return None
    k = canon(re.sub(SUFFIX, "", n.strip())); return k if k in plus else None

def fetch(url, path):
    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "tv-epg/1.0"})
            with urllib.request.urlopen(req, timeout=300) as r, open(path, "wb") as f:
                shutil.copyfileobj(r, f)
            with open(path, "rb") as f:
                if f.read(2) != b"\x1f\x8b": raise ValueError("не gzip")
            return True
        except Exception as e:
            print("download", url, attempt, e, file=sys.stderr); time.sleep(10)
    return False

now = dt.datetime.now(dt.timezone.utc)
lo, hi = now - dt.timedelta(hours=36), now + dt.timedelta(days=5)
paths = dict(a.split("=", 1) for a in sys.argv[1:])
out_ch, out_pr, stats, taken = [], [], {}, set()
for key, url in SOURCES.items():
    path = paths.get(key) or f"/tmp/{key}.xml.gz"
    if key not in paths and not fetch(url, path):
        print("источник", key, "недоступен, пропускаем", file=sys.stderr); continue
    chans, progs = {}, {}   # id -> (канон, имя);  id -> [строки programme]
    try:
        for ev, el in iterparse(gzip.open(path), events=("end",)):
            if el.tag == "channel":
                for dn in el.findall("display-name"):
                    b = base_channel(dn.text)
                    if b and b not in taken:
                        chans[el.get("id")] = (b, nice[b]); break
                el.clear()
            elif el.tag == "programme":
                ch = chans.get(el.get("channel"))
                if ch:
                    try: st = dt.datetime.strptime(el.get("start"), "%Y%m%d%H%M%S %z")
                    except Exception: el.clear(); continue
                    if lo <= st <= hi:
                        cid = f"{key}:{el.get('channel')}"
                        t = el.find("title"); title = ((t.text or "").strip() if t is not None else "")
                        progs.setdefault(el.get("channel"), []).append(
                            f"<programme start={quoteattr(fix_time(el.get('start')))} stop={quoteattr(fix_time(el.get('stop')))} channel={quoteattr(cid)}><title>{escape(title)}</title></programme>")
                el.clear()
    except Exception as e:
        print("ошибка чтения", key, e, file=sys.stderr)
    # на каждый канал — один вариант (с наибольшим числом передач)
    best = {}
    for i, pr in progs.items():
        b = chans[i][0]
        if b not in best or len(pr) > len(progs[best[b]]): best[b] = i
    nch = npr = 0
    for b, i in best.items():
        cid = f"{key}:{i}"
        out_ch.append(f"<channel id={quoteattr(cid)}><display-name>{escape(chans[i][1])}</display-name></channel>")
        out_pr.extend(progs[i]); taken.add(b); nch += 1; npr += len(progs[i])
    stats[key] = (nch, npr); print(key, "каналов:", nch, "передач:", npr)

missing = sorted(c for c in channels if canon(c) not in taken)
if missing: print("нет программы для:", ", ".join(missing))

if not out_pr or sum(n for n, _ in stats.values()) == 0:
    sys.exit("нет данных — файл не обновляем")
with gzip.open(OUT, "wt", encoding="utf-8", compresslevel=9) as f:
    f.write('<?xml version="1.0" encoding="UTF-8"?>\n<tv generated="%s" time-mode=%s>\n' % (now.strftime("%Y-%m-%d %H:%M UTC"), quoteattr(TIME_MODE)))
    f.write("\n".join(out_ch + out_pr)); f.write("\n</tv>\n")
print("готово:", OUT, os.path.getsize(OUT), "байт")
