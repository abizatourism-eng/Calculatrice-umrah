"""منطق حاسبة العمرة (بلا واجهة): التاريخ الهجري، حساب الليالي، التكلفة والربح،
مقارنة الغرف، قاعدة بيانات SQLite، وتوليد ملفات PDF.
تستورده الواجهة umra.py ويجب أن يبقى الملفان في المجلد نفسه.
"""
import json
import math
import os
import re
import sqlite3
import textwrap
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

# ألوان ملفات PDF ثابتة (فاتحة دائماً مهما كانت سمة الواجهة)
P_GREEN, P_INK, P_MUTED, P_LINE = "#1B6B4E", "#16231D", "#64736B", "#DDE5E0"
P_GREEN_SOFT, P_GOLD_SOFT, P_RED = "#E6F2EC", "#FBF4E2", "#B03A2E"

CHECK_TIME = time(12, 0)
CITIES = {"المدينة المنورة": "madina", "مكة المكرمة": "makka"}
NAMES = {"madina": "المدينة المنورة", "makka": "مكة المكرمة"}
AR_DAYS = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
HIJRI_MONTHS = ["محرم", "صفر", "ربيع الأول", "ربيع الآخر", "جمادى الأولى", "جمادى الآخرة",
                "رجب", "شعبان", "رمضان", "شوال", "ذو القعدة", "ذو الحجة"]
COMPARE_TYPES = (2, 3, 4, 5)
SIZE_NAMES = {2: "ثنائية", 3: "ثلاثية", 4: "رباعية", 5: "خماسية"}
REMEMBER = ["exchange", "visa", "taxes", "guide", "bags", "commission", "agency"]


# ========================= التاريخ الهجري (تقريبي) =========================
HIJRI_OFFSET_DAYS = 0    # تعديل لتقريب التقويم الحسابي من تقويم أم القرى؛ غيّره إن لزم (±1)


def to_hijri(d):
    """تحويل ميلادي ← هجري بالتقويم الحسابي؛ قد يختلف يوماً أو يومين عن رؤية الهلال."""
    d = d + timedelta(days=HIJRI_OFFSET_DAYS)
    jd = d.toordinal() + 1721425   # اليوم الجولياني (غريغوري)
    l = jd - 1948440 + 10632
    n = (l - 1) // 10631
    l = l - 10631 * n + 354
    j = ((10985 - l) // 5316) * ((50 * l) // 17719) + (l // 5670) * ((43 * l) // 15238)
    l = l - ((30 - j) // 15) * ((17719 * j) // 50) - (j // 16) * ((15238 * j) // 43) + 29
    month = (24 * l) // 709
    day = l - (709 * month) // 24
    year = 30 * n + j - 30
    return year, month, day


def hijri_text(d):
    y, m, day = to_hijri(d)
    return f"{day} {HIJRI_MONTHS[m - 1]} {y} هـ"


# ========================= نصوص وأدوات =========================
def unit_text(n, one, two, few, many):
    """صياغة العدد مع المعدود: واحد، اثنان، 3-10 جمع، وما فوق مفرد."""
    if n == 1:
        return one
    if n == 2:
        return two
    return f"{n} {few}" if 3 <= n <= 10 else f"{n} {many}"


def hours_text(delta):
    h = int(delta.total_seconds() // 3600)
    m = int(delta.total_seconds() % 3600 // 60)
    parts = []
    if h:
        parts.append(unit_text(h, "ساعة واحدة", "ساعتان", "ساعات", "ساعة"))
    if m:
        parts.append(unit_text(m, "دقيقة واحدة", "دقيقتان", "دقائق", "دقيقة"))
    return " و".join(parts) if parts else "أقل من دقيقة"


def nights_text(n):
    return unit_text(n, "ليلة واحدة", "ليلتان", "ليالٍ", "ليلة")


def persons_text(n):
    return unit_text(n, "شخص واحد", "شخصان", "أشخاص", "شخصاً")


def rooms_text(n):
    return unit_text(n, "غرفة", "غرفتان", "غرف", "غرفة")


def pilgrims_text(n):
    return unit_text(n, "معتمر واحد", "معتمران", "معتمرين", "معتمراً")


def label(d):
    return f"{AR_DAYS[d.weekday()]} {d:%Y-%m-%d} الساعة {d:%H:%M}"


def date_line(d):
    return f"{AR_DAYS[d.weekday()]} {d:%Y-%m-%d} الساعة {d:%H:%M} ({hijri_text(d)})"


def money(x, dec=2):
    return f"{x:,.{dec}f} دج"


def split_money(value):
    """يفصل المبلغ عن الوحدة: '1,000.00 دج' ← ('1,000.00', 'دج')"""
    if value.endswith(" دج"):
        return value[:-3], "دج"
    return value, ""


def unique_path(folder, filename):
    """مسار ملف جديد داخل المجلد دون الكتابة فوق ملف موجود: اسم.pdf ← اسم (2).pdf"""
    folder = Path(folder)
    path = folder / filename
    stem, suffix, n = path.stem, path.suffix, 2
    while path.exists():
        path = folder / f"{stem} ({n}){suffix}"
        n += 1
    return path


def safe_filename(name):
    return re.sub(r'[\\/:*?"<>|]+', "_", name).strip() or "تقرير"



# ========================= قراءة المدخلات =========================
class InputError(Exception):
    """خطأ في حقل محدد"""

    def __init__(self, field, reason):
        super().__init__(f"{field}: {reason}")
        self.field = field
        self.reason = reason


_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def norm(text):
    """توحيد الأرقام العربية/الفارسية والفواصل"""
    return text.translate(_DIGITS).replace("٫", ".").replace("٬", ",").replace("\u200f", "")


def _clean(text):
    t = norm(text).strip().replace(" ", "")
    if re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", t):   # 1,234,567.50 ← فاصل آلاف
        return t.replace(",", "")
    return t.replace(",", ".").replace("،", ".")


@dataclass
class Segment:
    city: str
    check_in: datetime
    check_out: datetime
    nights: int


def noon(d):
    return datetime.combine(d.date(), CHECK_TIME)


def hotel_start(arrival, early):
    start = noon(arrival)
    if arrival < start and early == "previous":
        start -= timedelta(days=1)
    return start


def calculate_stay(arrival, departure, first, first_nights, early):
    if departure <= arrival:
        raise ValueError("موعد المغادرة يجب أن يكون بعد موعد الوصول.")
    start, end = hotel_start(arrival, early), noon(departure)
    total = (end - start).days
    if total < 1:
        raise ValueError("المدة لا تكفي لليلة فندقية كاملة.")
    if not 0 <= first_nights <= total:
        raise ValueError(f"الليالي في المدينة الأولى يجب أن تكون بين 0 و {total}.")
    second = "makka" if first == "madina" else "madina"
    mid = start + timedelta(days=first_nights)
    segs = []
    if first_nights:
        segs.append(Segment(first, start, mid, first_nights))
    if total - first_nights:
        segs.append(Segment(second, mid, end, total - first_nights))
    return start, end, total, segs


# ========================= منطق التكلفة والربح =========================
@dataclass
class Row:
    label: str
    text: str
    bold: bool = False
    tone: str = None     # "pos" | "neg" | None
    raw: float = None


def hotel_pp(h, rate):
    """تكلفة الإقامة للفرد: سعر الغرفة × الليالي × سعر الصرف ÷ سعة الغرفة."""
    return h["price"] * h["nights"] * rate / h["room"]


def category_costs(v, mk, md):
    """تكلفة البالغ والطفل والرضيع لقيمتي الإقامة (مكة، المدينة) للفرد."""
    hot = mk + md
    other = v["taxes"] + v["guide"] + v["bags"] + v["commission"]
    adult = hot + v["flight"] + v["visa"] + other
    child = hot + v["child_flight"] + v["child_visa"] + other
    infant = v["infant_flight"] + v["infant_visa"]
    return adult, child, infant, other


def compute_trip(v, stay=None, default_rate=None):
    rate = v["exchange"]
    mk, md = hotel_pp(v["mk"], rate), hotel_pp(v["md"], rate)
    a_cost, c_cost, i_cost, other = category_costs(v, mk, md)
    adults, children, infants = v["adults"], v["children"], v["infants"]
    heads = adults + children + infants

    cats = []
    for key, name, count, cost, sell in (
            ("adult", "البالغ", adults, a_cost, v["sell_adult"]),
            ("child", "الطفل", children, c_cost, v["sell_child"]),
            ("infant", "الرضيع", infants, i_cost, v["sell_infant"])):
        cats.append({"key": key, "name": name, "count": count, "cost": cost, "sell": sell,
                     "profit": None if sell is None else sell - cost})
    total_cost = sum(c["count"] * c["cost"] for c in cats)
    counted = [c for c in cats if c["count"] > 0]
    revenue = profit_total = margin = None
    if counted and all(c["sell"] is not None for c in counted):
        revenue = sum(c["count"] * c["sell"] for c in counted)
        profit_total = revenue - total_cost
        margin = profit_total / revenue * 100 if revenue else None

    # الأسرّة والغرف والتنبيهات
    beds = adults + children      # الرضيع بلا سرير
    alerts, rooms = [], {}
    for key, name, h, pp in (("mk", "مكة", v["mk"], mk), ("md", "المدينة", v["md"], md)):
        if beds:
            rooms[key] = math.ceil(beds / h["room"])
            empty = rooms[key] * h["room"] - beds
            if empty > 0 and pp > 0:
                alerts.append((f"غرف {name}: {unit_text(empty, 'سرير واحد فارغ', 'سريران فارغان', 'أسرّة فارغة', 'سريراً فارغاً')} "
                               f"في الغرفة الأخيرة، وتكلفتها التقريبية {empty * pp:,.0f} دج لا يتحملها أحد.", "warn"))
    if stay:
        sm, sd = stay["nights"].get("makka", 0), stay["nights"].get("madina", 0)
        if (sm, sd) != (v["mk"]["nights"], v["md"]["nights"]):
            alerts.append((f"ليالي حاسبة الأيام (مكة {sm}، المدينة {sd}) تختلف عن ليالي التكلفة "
                           f"(مكة {v['mk']['nights']}، المدينة {v['md']['nights']}).", "warn"))
    if default_rate and abs(rate - default_rate) / default_rate > 0.15:
        alerts.append((f"سعر الصرف ({rate:g}) يختلف بأكثر من 15% عن آخر قيمة محفوظة ({default_rate:g}).", "warn"))
    for c in counted:
        if c["profit"] is not None and c["profit"] < 0:
            alerts.append((f"سعر بيع {c['name']} أقل من تكلفته بمقدار {abs(c['profit']):,.0f} دج للفرد.", "err"))
    if profit_total is not None and profit_total < 0:
        alerts.append((f"الرحلة بخسارة إجمالية قدرها {abs(profit_total):,.0f} دج.", "err"))

    # صفوف التقرير
    rows = []
    if adults:
        rows.append(Row("عدد البالغين", str(adults)))
    if children:
        rows.append(Row("عدد الأطفال", str(children)))
    if infants:
        rows.append(Row("عدد الرضّع", str(infants)))
    rows += [Row("ليالي مكة", str(v["mk"]["nights"])), Row("ليالي المدينة", str(v["md"]["nights"]))]
    if "mk" in rooms:
        rows.append(Row("عدد الغرف في مكة", str(rooms["mk"])))
    if "md" in rooms:
        rows.append(Row("عدد الغرف في المدينة", str(rooms["md"])))
    rows += [Row("تكلفة إقامة مكة (للفرد)", money(mk), raw=mk),
             Row("تكلفة إقامة المدينة (للفرد)", money(md), raw=md),
             Row("تكلفة الطيران (للبالغ)", money(v["flight"]), raw=v["flight"]),
             Row("الخدمات والثوابت (للبالغ)", money(v["visa"] + other), raw=v["visa"] + other)]
    if children:
        rows.append(Row("تكلفة الطفل الواحد", money(c_cost), raw=c_cost))
    if infants:
        rows.append(Row("تكلفة الرضيع الواحد", money(i_cost), raw=i_cost))
    rows.append(Row("تكلفة البالغ الواحد" if (children or infants) else "تكلفة الفرد الواحد",
                    money(a_cost), True, None, a_cost))
    if heads:
        rows.append(Row(f"التكلفة الكلية لـ {heads} مسافر", money(total_cost), True, None, total_cost))
    tone = lambda x: "pos" if x >= 0 else "neg"
    if profit_total is not None:
        cap = f"الربح الكلي (هامش {margin:.1f}%)" if margin is not None else "الربح الكلي"
        rows.append(Row(cap, money(profit_total), True, tone(profit_total), profit_total))
    elif cats[0]["profit"] is not None:
        rows.append(Row("ربح البالغ الواحد", money(cats[0]["profit"]), True, tone(cats[0]["profit"]),
                        cats[0]["profit"]))

    return {"cats": cats, "heads": heads, "beds": beds, "total_cost": total_cost, "revenue": revenue,
            "profit_total": profit_total, "margin": margin, "rows": rows, "alerts": alerts,
            "rooms": rooms, "mk": mk, "md": md}


def room_comparison(v):
    """تكلفة الرحلة لو كانت الغرفة 2 و3 و4 و5 ... في الفندقين، مع تعليم الحالي والأوفر."""
    rate = v["exchange"]
    cur_mk, cur_md = v["mk"]["room"], v["md"]["room"]
    adults, children, infants = v["adults"], v["children"], v["infants"]
    heads = adults + children + infants
    beds = adults + children
    rows = []
    for n in sorted(set(COMPARE_TYPES) | {cur_mk, cur_md}):
        mk = v["mk"]["price"] * v["mk"]["nights"] * rate / n
        md = v["md"]["price"] * v["md"]["nights"] * rate / n
        a, c, i, _ = category_costs(v, mk, md)
        rooms = math.ceil(beds / n) if beds else None
        total = a * adults + c * children + i * infants if heads else None
        rows.append({"type": n, "rooms": rooms, "makkah": mk, "madinah": md, "per": a, "total": total,
                     "current": cur_mk == cur_md == n})
    lo, hi = min(r["per"] for r in rows), max(r["per"] for r in rows)
    for r in rows:
        r["best"] = hi - lo > 0.005 and r["per"] - lo < 0.005
        r["label"] = persons_text(r["type"]) + (f" ({rooms_text(r['rooms'])})" if r["rooms"] else "")
        r["tag"] = ("الحالي - أقل سعر" if r["current"] and r["best"]
                    else "الحالي" if r["current"] else "أقل سعر" if r["best"] else "")
        r["total_text"] = f"{r['total']:,.0f}" if r["total"] is not None else "—"
    return rows


def category_table(R, v):
    """رأس وصفوف جدول الفئات (للشاشة وPDF)؛ يُرجع (None, []) إن لم يلزم."""
    cats = R["cats"]
    show = [c for c in cats if c["count"] > 0 or (c["key"] == "adult" and c["sell"] is not None)]
    has_sell = any(c["sell"] is not None for c in show)
    if not show or (len(show) == 1 and not has_sell):
        return None, []
    head = ["الفئة", "العدد", "التكلفة للفرد"] + (["سعر البيع", "الربح للفرد"] if has_sell else [])
    rows = []
    for c in show:
        r = [c["name"], str(c["count"]), f"{c['cost']:,.0f}"]
        if has_sell:
            r += [f"{c['sell']:,.0f}" if c["sell"] is not None else "—",
                  f"{c['profit']:,.0f}" if c["profit"] is not None else "—"]
        rows.append(r)
    return head, rows


def build_report_text(name, rows, alerts, compare, cat_head, cat_rows, stay):
    lines = ["التقرير المالي المفصل للعمرة"]
    if name:
        lines.append(f"الرحلة: {name}")
    if stay:
        lines += [f"الوصول: {date_line(stay['arrival'])}", f"المغادرة: {date_line(stay['departure'])}"]
    lines += [f"{r.label}: {r.text}" for r in rows]
    if cat_head:
        lines += ["", "الفئات:"] + ["، ".join(f"{h}: {x}" for h, x in zip(cat_head, r)) for r in cat_rows]
    if compare:
        lines += ["", "مقارنة أنواع الغرف:"]
        for r in compare:
            tag = f" [{r['tag']}]" if r["tag"] else ""
            total = f"، الكلي {r['total']:,.0f} دج" if r["total"] is not None else ""
            lines.append(f"{r['label']}: للفرد {r['per']:,.0f} دج{total}{tag}")
    if alerts:
        lines += ["", "تنبيهات:"] + [f"- {t}" for t, _ in alerts]
    return "\n".join(lines)


# ========================= قاعدة البيانات =========================
class Store:
    """رحلات محفوظة وإعدادات في SQLite"""

    def __init__(self, path):
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS trips (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                created TEXT NOT NULL, updated TEXT NOT NULL,
                state TEXT NOT NULL, summary TEXT NOT NULL DEFAULT '{}');
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
        self.db.commit()

    @staticmethod
    def _now():
        return datetime.now().isoformat(sep=" ", timespec="seconds")

    def save_trip(self, trip_id, name, state, summary):
        now = self._now()
        if trip_id and self.db.execute("SELECT 1 FROM trips WHERE id=?", (trip_id,)).fetchone():
            self.db.execute("UPDATE trips SET name=?, updated=?, state=?, summary=? WHERE id=?",
                            (name, now, json.dumps(state, ensure_ascii=False),
                             json.dumps(summary, ensure_ascii=False), trip_id))
        else:
            cur = self.db.execute(
                "INSERT INTO trips (name, created, updated, state, summary) VALUES (?,?,?,?,?)",
                (name, now, now, json.dumps(state, ensure_ascii=False),
                 json.dumps(summary, ensure_ascii=False)))
            trip_id = cur.lastrowid
        self.db.commit()
        return trip_id

    def list_trips(self):
        out = []
        for r in self.db.execute("SELECT id, name, created, updated, summary FROM trips ORDER BY updated DESC, id DESC"):
            out.append({"id": r["id"], "name": r["name"], "created": r["created"],
                        "updated": r["updated"], "summary": json.loads(r["summary"] or "{}")})
        return out

    def get_trip(self, trip_id):
        r = self.db.execute("SELECT * FROM trips WHERE id=?", (trip_id,)).fetchone()
        if not r:
            return None
        return {"id": r["id"], "name": r["name"], "state": json.loads(r["state"]),
                "summary": json.loads(r["summary"] or "{}")}

    def delete_trip(self, trip_id):
        self.db.execute("DELETE FROM trips WHERE id=?", (trip_id,))
        self.db.commit()

    def duplicate_trip(self, trip_id):
        t = self.get_trip(trip_id)
        if not t:
            return None
        state = json.loads(json.dumps(t["state"]))
        new_name = f"{t['name']} (نسخة)"
        state.setdefault("cost", {})["trip_name"] = new_name
        return self.save_trip(None, new_name, state, t["summary"])

    def get(self, key, default=None):
        r = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(r["value"]) if r else default

    def set(self, key, value):
        self.db.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, json.dumps(value, ensure_ascii=False)))
        self.db.commit()


def open_store():
    folders = []
    if os.environ.get("FLET_APP_STORAGE_DATA"):      # مجلد بيانات التطبيق على أندرويد
        folders.append(Path(os.environ["FLET_APP_STORAGE_DATA"]))
    folders += [Path(__file__).parent, Path.home()]
    for folder in folders:
        try:
            folder.mkdir(parents=True, exist_ok=True)
            return Store(folder / "umrah_trips.db")
        except (sqlite3.Error, OSError):
            continue
    return Store(":memory:")


# ========================= ملفات PDF =========================
class MissingDependency(Exception):
    """مكتبة أو خط ناقص؛ الرسالة تُعرض للمستخدم"""


FONT_CANDIDATES = [
    # (عادي، عريض)
    (r"C:\Windows\Fonts\tahoma.ttf", r"C:\Windows\Fonts\tahomabd.ttf"),
    (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\arialbd.ttf"),
    ("/Library/Fonts/Arial Unicode.ttf", None),
    ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf", None),
]


def find_font():
    for regular, bold in FONT_CANDIDATES:
        if os.path.exists(regular):
            return regular, (bold if bold and os.path.exists(bold) else regular)
    return None, None


def make_pdf(path, title, subtitles, sections):
    """ينشئ PDF عربياً. الأعمدة تُعطى بترتيب القراءة (الأول في أقصى اليمين)."""
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError:
        raise MissingDependency("لحفظ ملفات PDF ثبّت المكتبات التالية ثم أعد المحاولة:\n\n"
                                "pip install reportlab arabic-reshaper python-bidi")
    regular, bold = find_font()
    if not regular:
        raise MissingDependency("لم يُعثر على خط يدعم العربية (مثل Tahoma أو Arial) على هذا الجهاز.")
    pdfmetrics.registerFont(TTFont("RFont", regular))
    pdfmetrics.registerFont(TTFont("RFontB", bold))

    def ar(text):
        return escape(get_display(arabic_reshaper.reshape(text)))

    def wrapped(text, width=70):
        return "<br/>".join(ar(line) for line in textwrap.wrap(text, width) or [""])

    def style(name, font, size, align, color, leading):
        return ParagraphStyle(name, fontName=font, fontSize=size, alignment=align,
                              textColor=colors.HexColor(color), leading=leading)

    title_st = style("t", "RFontB", 18, TA_CENTER, P_GREEN, 26)
    sub_st = style("s", "RFont", 10, TA_CENTER, P_MUTED, 16)
    head_st = style("h", "RFontB", 13, TA_RIGHT, P_INK, 20)
    note_st = style("n", "RFont", 9, TA_RIGHT, P_MUTED, 14)
    aligns = {"R": TA_RIGHT, "C": TA_CENTER, "L": TA_LEFT}

    story = [Paragraph(ar(title), title_st), Spacer(1, 2)]
    for line in subtitles:
        story.append(Paragraph(ar(line), sub_st))
    story.append(Spacer(1, 14))

    for sec in sections:
        kind = sec["type"]
        if kind == "heading":
            story += [Spacer(1, 14), Paragraph(ar(sec["text"]), head_st), Spacer(1, 4)]
        elif kind == "note":
            story += [Spacer(1, 4), Paragraph(wrapped(sec["text"]), note_st)]
        elif kind == "table":
            ncols = len(sec["widths"])
            al = sec.get("aligns") or ["R"] + ["C"] * (ncols - 1)
            bold_rows, tint, row_colors = sec.get("bold", set()), sec.get("tint", {}), sec.get("colors", {})
            data, styles = [], [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor(P_LINE)),
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor(P_LINE))]
            offset = 0
            if sec.get("head"):
                data.append([Paragraph(ar(h), style("hh", "RFontB", 9.5, aligns[a], P_GREEN, 14))
                             for h, a in zip(sec["head"], al)][::-1])
                styles.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(P_GREEN_SOFT)))
                offset = 1
            for i, row in enumerate(sec["rows"]):
                is_bold = i in bold_rows
                color = row_colors.get(i, P_GREEN if is_bold else P_INK)
                data.append([Paragraph(ar(str(c)), style("c", "RFontB" if is_bold else "RFont",
                                                         10.5 if is_bold else 10, aligns[a], color, 15))
                             for c, a in zip(row, al)][::-1])
                if i in tint:
                    styles.append(("BACKGROUND", (0, i + offset), (-1, i + offset), colors.HexColor(tint[i])))
            table = Table(data, colWidths=[w * cm for w in reversed(sec["widths"])])
            table.setStyle(TableStyle(styles))
            story.append(table)

    SimpleDocTemplate(path, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                      topMargin=2 * cm, bottomMargin=2 * cm, title=title).build(story)
