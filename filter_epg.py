#!/usr/bin/env python3
"""Скачивает большие XMLTV-файлы, оставляет только каналы из list.md и недавние передачи.
Результат: epg_small.xml.gz (около 1 МБ). Запуск: python filter_epg.py [a=путь b=путь]  (пути — для проверки без сети)"""
import gzip, re, sys, os, time, datetime as dt, urllib.request, shutil
from xml.etree.ElementTree import iterparse
from xml.sax.saxutils import escape, quoteattr

SOURCES = {"a": "https://github.com/mireamor/my_epg/releases/download/latest/epg.xml.gz",
           "b": "https://raw.githubusercontent.com/Lorax121/epg_v2/main/data/epg2.xml.gz"}
OUT = "epg_small.xml.gz"
ALIAS = {"5канал": "пятыйканал", "твц": "твцентр", "россиякультура": "россияк", "ru-tv": "rutv"}
SUFFIX = r"(\s+(fhd|uhd|hd|4k|orig|50))+$"
def canon(s):
    k = re.sub(r"[\s.!\-–—]", "", (s or "").lower().replace("ё", "е")); return ALIAS.get(k, k)

channels = []
for line in open("list.md", encoding="utf-8"):
    m = re.match(r"^[-*•]\s+(.+)$", line.strip())
    if m: channels.append(re.sub(r"\\(.)", r"\1", m.group(1)).strip())
plus = {canon(c) for c in channels}
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
out_ch, out_pr, stats = [], [], {}
for key, url in SOURCES.items():
    path = paths.get(key) or f"/tmp/{key}.xml.gz"
    if key not in paths and not fetch(url, path):
        print("источник", key, "недоступен, пропускаем", file=sys.stderr); continue
    chans, nch, npr = {}, 0, 0
    try:
        for ev, el in iterparse(gzip.open(path), events=("end",)):
            if el.tag == "channel":
                for dn in el.findall("display-name"):
                    if base_channel(dn.text):
                        cid = f"{key}:{el.get('id')}"; chans[el.get("id")] = cid
                        out_ch.append(f"<channel id={quoteattr(cid)}><display-name>{escape(dn.text.strip())}</display-name></channel>")
                        nch += 1; break
                el.clear()
            elif el.tag == "programme":
                cid = chans.get(el.get("channel"))
                if cid:
                    try: st = dt.datetime.strptime(el.get("start"), "%Y%m%d%H%M%S %z")
                    except Exception: el.clear(); continue
                    if lo <= st <= hi:
                        t = el.find("title"); title = ((t.text or "").strip() if t is not None else "")
                        out_pr.append(f"<programme start={quoteattr(el.get('start'))} stop={quoteattr(el.get('stop'))} channel={quoteattr(cid)}><title>{escape(title)}</title></programme>")
                        npr += 1
                el.clear()
    except Exception as e:
        print("ошибка чтения", key, e, file=sys.stderr)
    stats[key] = (nch, npr); print(key, "каналов:", nch, "передач:", npr)

if not out_pr or sum(n for n, _ in stats.values()) == 0:
    sys.exit("нет данных — файл не обновляем")
with gzip.open(OUT, "wt", encoding="utf-8", compresslevel=9) as f:
    f.write('<?xml version="1.0" encoding="UTF-8"?>\n<tv generated="%s">\n' % now.strftime("%Y-%m-%d %H:%M UTC"))
    f.write("\n".join(out_ch + out_pr)); f.write("\n</tv>\n")
print("готово:", OUT, os.path.getsize(OUT), "байт")
