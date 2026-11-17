"""حاسبة العمرة المتكاملة - نسخة أندرويد (Flet). المنطق كله في umra_logic.py."""
from datetime import datetime, timedelta

import flet as ft

from umra_logic import (
    CITIES, NAMES, InputError, _clean, build_report_text, calculate_stay, category_table,
    compute_trip, date_line, hijri_text, hours_text, label, nights_text, norm, open_store,
    room_comparison)

GREEN, GOLD, RED, MUTED = "#1B6B4E", "#B07F22", "#B03A2E", "#64736B"

# (المفتاح، العنوان، القيمة الافتراضية)
COST_SECTIONS = [
    ("البيانات الأساسية", [("trip_name", "اسم الرحلة", ""), ("persons", "عدد المعتمرين", ""),
                           ("flight", "سعر تذكرة الطيران", ""), ("exchange", "سعر الصرف", "68")]),
    ("فندق مكة المكرمة", [("makkah_price", "سعر الغرفة لليلة", ""),
                          ("makkah_nights", "عدد الليالي", "12"), ("makkah_room", "نوع الغرفة (عدد الأسرّة)", "4")]),
    ("فندق المدينة المنورة", [("madinah_price", "سعر الغرفة لليلة", ""),
                              ("madinah_nights", "عدد الليالي", "3"), ("madinah_room", "نوع الغرفة (عدد الأسرّة)", "4")]),
    ("الثوابت والخدمات (للفرد)", [("visa", "التأشيرة", "50000"), ("taxes", "الضرائب", "1000"),
                                  ("guide", "المرشد", "2000"), ("bags", "خدمات", "3000"),
                                  ("commission", "كوميسيو", "15000")]),
    ("الأطفال والرضّع (اختياري)", [("children", "عدد الأطفال", ""), ("child_flight", "تذكرة الطفل", ""),
                                   ("child_visa", "تأشيرة الطفل", ""), ("infants", "عدد الرضّع", ""),
                                   ("infant_flight", "تذكرة الرضيع", ""), ("infant_visa", "تأشيرة الرضيع", "")]),
    ("التسعير والربح (اختياري)", [("sell_adult", "سعر بيع البالغ", ""), ("sell_child", "سعر بيع الطفل", ""),
                                  ("sell_infant", "سعر بيع الرضيع", ""), ("agency", "اسم الوكالة", "")]),
]
TEXT_KEYS = {"trip_name", "agency"}
REMEMBER = ["exchange", "visa", "taxes", "guide", "bags", "commission", "agency"]


def Btn(text, on_click, primary=True):
    cls = getattr(ft, "FilledButton", None) or ft.ElevatedButton
    if not primary:
        cls = getattr(ft, "OutlinedButton", cls)
    return cls(text, on_click=on_click)


def Note(text, color=MUTED, bold=False, size=14):
    return ft.Text(text, color=color, size=size, text_align=ft.TextAlign.RIGHT,
                   weight=ft.FontWeight.BOLD if bold else None)


def Card(*controls):
    return ft.Container(ft.Column(list(controls), spacing=8), padding=12, border_radius=12,
                        border=ft.border.all(1, "#DDE5E0"))


def parse_float(raw, field, optional=False, strict=False):
    t = _clean(raw or "")
    if not t:
        if optional:
            return None
        if strict:
            raise InputError(field, "الحقل مطلوب.")
        return 0.0
    try:
        x = float(t)
    except ValueError:
        raise InputError(field, "أدخل رقماً صحيحاً.")
    if x < 0 or (strict and x <= 0):
        raise InputError(field, "القيمة غير مقبولة.")
    return x


def parse_int(raw, field, minimum=0, optional=False):
    t = _clean(raw or "")
    if not t and optional:
        return 0
    try:
        x = int(float(t))
    except ValueError:
        raise InputError(field, "أدخل عدداً صحيحاً.")
    if x < minimum:
        raise InputError(field, f"يجب ألا يقل عن {minimum}.")
    return x


def main(page: ft.Page):
    page.title = "حاسبة العمرة"
    page.scroll = None
    page.padding = 0
    store = open_store()

    # ---------------- حالة مشتركة ----------------
    stay_info = {"data": None}
    cost_fields = {}
    state = {"trip_id": None}

    def copy_text(text):
        try:
            page.set_clipboard(text)
        except Exception:
            try:
                page.run_task(ft.Clipboard().set, text)
            except Exception:
                pass
        snack("تم النسخ")

    def snack(msg):
        try:
            page.show_dialog(ft.SnackBar(ft.Text(msg)))
        except Exception:
            page.snack_bar = ft.SnackBar(ft.Text(msg))
            page.snack_bar.open = True
            page.update()

    # ---------------- تبويب الإقامة ----------------
    now = datetime.now()
    d_arr = (now + timedelta(days=7)).replace(hour=14, minute=0, second=0, microsecond=0)
    d_dep = (now + timedelta(days=17)).replace(hour=10, minute=0, second=0, microsecond=0)
    arr_f = ft.TextField(label="وصول الرحلة (YYYY-MM-DD HH:MM)", value=d_arr.strftime("%Y-%m-%d %H:%M"))
    dep_f = ft.TextField(label="إقلاع رحلة العودة (YYYY-MM-DD HH:MM)", value=d_dep.strftime("%Y-%m-%d %H:%M"))
    city_f = ft.Dropdown(label="المدينة الأولى", value="المدينة المنورة",
                         options=[ft.dropdown.Option(c) for c in CITIES])
    nights_f = ft.TextField(label="الليالي في المدينة الأولى", value="4",
                            keyboard_type=ft.KeyboardType.NUMBER)
    early_f = ft.RadioGroup(value="previous", content=ft.Column([
        ft.Radio(value="previous", label="حجز الليلة السابقة"),
        ft.Radio(value="wait", label="الانتظار حتى الظهر")]))
    stay_out = ft.Column(spacing=8)

    def calc_stay(e=None):
        stay_out.controls.clear()
        stay_info["data"] = None
        try:
            arrival = datetime.strptime(norm(arr_f.value).strip(), "%Y-%m-%d %H:%M")
            departure = datetime.strptime(norm(dep_f.value).strip(), "%Y-%m-%d %H:%M")
        except ValueError:
            stay_out.controls.append(Note("التاريخ غير صحيح. الصيغة: 2026-12-20 14:00", RED))
            return page.update()
        try:
            n1 = int(norm(nights_f.value))
            start, end, total, segs = calculate_stay(arrival, departure, CITIES[city_f.value], n1,
                                                     early_f.value)
        except ValueError as err:
            stay_out.controls.append(Note(str(err) if "invalid literal" not in str(err)
                                          else "أدخل عدد الليالي كرقم صحيح.", RED))
            return page.update()
        lines = [f"الوصول: {date_line(arrival)}", f"المغادرة: {date_line(departure)}",
                 f"إجمالي الليالي الفندقية: {total}"]
        stay_out.controls.append(Note(f"إجمالي الليالي الفندقية: {total}", GREEN, True, 20))
        nights = {"makka": 0, "madina": 0}
        for s in segs:
            nights[s.city] += s.nights
            stay_out.controls.append(Card(
                Note(f"{NAMES[s.city]} - {nights_text(s.nights)}", GREEN, True, 16),
                Note(f"دخول: {label(s.check_in)}"), Note(hijri_text(s.check_in), MUTED, size=12),
                Note(f"خروج: {label(s.check_out)}"), Note(hijri_text(s.check_out), MUTED, size=12)))
            lines.append(f"{NAMES[s.city]}: {nights_text(s.nights)} (دخول {label(s.check_in)}، "
                         f"خروج {label(s.check_out)})")
        notes = []
        if start.date() < arrival.date():
            notes.append("تم احتساب ليلة إضافية قبل الوصول لأن الوصول قبل 12 ظهراً.")
        if start > arrival:
            notes.append(f"انتظار {hours_text(start - arrival)} بين الوصول ودخول الغرفة.")
        if end < departure:
            notes.append(f"{hours_text(departure - end)} بين الخروج من الفندق والإقلاع، يلزم حفظ الأمتعة.")
        stay_out.controls += [Note(n, GOLD) for n in notes]
        report = "\n".join(lines + notes)
        stay_info["data"] = {"arrival": arrival, "departure": departure, "nights": nights}

        def transfer(_):
            cost_fields["makkah_nights"].value = str(nights["makka"])
            cost_fields["madinah_nights"].value = str(nights["madina"])
            snack("تم اعتماد الليالي في حاسبة التكلفة")
            show(1)

        stay_out.controls.append(ft.Row([Btn("نسخ النتيجة", lambda _: copy_text(report), False),
                                         Btn("اعتماد الليالي في التكلفة", transfer)], wrap=True))
        page.update()

    stay_view = ft.Column([
        Card(arr_f, dep_f), Card(city_f, nights_f, Note("عند الوصول قبل 12 ظهراً:"), early_f),
        Btn("احسب الإقامة", calc_stay), stay_out], spacing=12)

    # ---------------- تبويب التكلفة ----------------
    last = store.get("last_values", {}) or {}
    cost_children = []
    for title, fields in COST_SECTIONS:
        ctrls = [Note(title, GREEN, True, 16)]
        for key, lab, default in fields:
            tf = ft.TextField(label=lab, value=last.get(key, default) if key in REMEMBER else default,
                              keyboard_type=ft.KeyboardType.TEXT if key in TEXT_KEYS
                              else ft.KeyboardType.NUMBER)
            cost_fields[key] = tf
            ctrls.append(tf)
        cost_children.append(Card(*ctrls))
    cost_out = ft.Column(spacing=8)
    cost_report = {"text": "", "R": None, "v": None}

    def parse_inputs():
        f = {k: tf.value for k, tf in cost_fields.items()}
        opt = lambda k, n: parse_float(f[k], n, optional=True)

        def hotel(prefix, name):
            return {"price": parse_float(f[f"{prefix}_price"], f"سعر غرفة {name}"),
                    "nights": parse_int(f[f"{prefix}_nights"], f"ليالي {name}"),
                    "room": parse_int(f[f"{prefix}_room"], f"نوع غرفة {name}", 1)}

        v = {"adults": parse_int(f["persons"], "عدد البالغين", optional=True),
             "children": parse_int(f["children"], "عدد الأطفال", optional=True),
             "infants": parse_int(f["infants"], "عدد الرضّع", optional=True),
             "flight": parse_float(f["flight"], "سعر تذكرة الطيران"),
             "exchange": parse_float(f["exchange"], "سعر الصرف", strict=True),
             "mk": hotel("makkah", "مكة"), "md": hotel("madinah", "المدينة"),
             "visa": parse_float(f["visa"], "التأشيرة"), "taxes": parse_float(f["taxes"], "الضرائب"),
             "guide": parse_float(f["guide"], "المرشد"), "bags": parse_float(f["bags"], "الخدمات"),
             "commission": parse_float(f["commission"], "الكوميسيو"),
             "child_flight": 0.0, "child_visa": 0.0, "infant_flight": 0.0, "infant_visa": 0.0,
             "sell_adult": opt("sell_adult", "سعر بيع البالغ"), "sell_child": opt("sell_child", "سعر بيع الطفل"),
             "sell_infant": opt("sell_infant", "سعر بيع الرضيع"),
             "name": f["trip_name"].strip(), "agency": f["agency"].strip()}
        if v["children"]:
            v["child_flight"] = parse_float(f["child_flight"], "تذكرة الطفل")
            v["child_visa"] = parse_float(f["child_visa"], "تأشيرة الطفل")
        if v["infants"]:
            v["infant_flight"] = parse_float(f["infant_flight"], "تذكرة الرضيع")
            v["infant_visa"] = parse_float(f["infant_visa"], "تأشيرة الرضيع")
        return v

    def calc_cost(e=None):
        cost_out.controls.clear()
        try:
            v = parse_inputs()
        except InputError as err:
            cost_out.controls.append(Note(f"{err.field}: {err.reason}", RED))
            return page.update()
        R = compute_trip(v, stay_info["data"], store.get("last_values", {}).get("exchange_num"))
        compare = room_comparison(v)
        head, rows = category_table(R, v)
        for text, level in R["alerts"]:
            cost_out.controls.append(Note(text, RED if level == "err" else GOLD))
        for r in R["rows"]:
            color = GREEN if r.tone == "pos" else RED if r.tone == "neg" else None
            cost_out.controls.append(ft.Row([
                ft.Text(r.text, weight=ft.FontWeight.BOLD if r.bold else None, color=color),
                ft.Text(r.label, expand=True, text_align=ft.TextAlign.RIGHT,
                        weight=ft.FontWeight.BOLD if r.bold else None)],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN))
        if head:
            cost_out.controls.append(Note("الفئات", GREEN, True, 16))
            for r in rows:
                cost_out.controls.append(Note("، ".join(f"{h}: {x}" for h, x in zip(head, r))))
        if compare:
            cost_out.controls.append(Note("مقارنة أنواع الغرف", GREEN, True, 16))
            for r in compare:
                tag = f" [{r['tag']}]" if r["tag"] else ""
                cost_out.controls.append(Note(f"{r['label']}: للفرد {r['per']:,.0f} دج{tag}"))
        stay = stay_info["data"]
        cost_report.update(text=build_report_text(v["name"], R["rows"], R["alerts"], compare, head,
                                                  rows, stay), R=R, v=v)
        cost_out.controls.append(ft.Row([
            Btn("نسخ التقرير", lambda _: copy_text(cost_report["text"]), False),
            Btn("حفظ الرحلة", save_trip)], wrap=True))
        store.set("last_values", {**{k: cost_fields[k].value for k in REMEMBER},
                                  "exchange_num": v["exchange"]})
        page.update()

    def save_trip(e=None):
        v, R = cost_report["v"], cost_report["R"]
        if not v:
            return
        name = v["name"] or f"رحلة {datetime.now():%Y-%m-%d %H:%M}"
        st = {"cost": {k: tf.value for k, tf in cost_fields.items()},
              "stay": {"arr": arr_f.value, "dep": dep_f.value, "city": city_f.value,
                       "nights": nights_f.value, "early": early_f.value}}
        summary = {"per": R["cats"][0]["cost"], "persons": v["adults"] or None, "sell": v["sell_adult"],
                   "total": R["total_cost"]}
        state["trip_id"] = store.save_trip(state["trip_id"], name, st, summary)
        snack("تم حفظ الرحلة")

    cost_view = ft.Column([*cost_children, Btn("احسب التكلفة والربح", calc_cost), cost_out], spacing=12)

    # ---------------- تبويب الرحلات المحفوظة ----------------
    trips_col = ft.Column(spacing=8)

    def load_trip(tid):
        t = store.get_trip(tid)
        if not t:
            return
        for k, val in t["state"].get("cost", {}).items():
            if k in cost_fields:
                cost_fields[k].value = val
        s = t["state"].get("stay", {})
        arr_f.value, dep_f.value = s.get("arr", arr_f.value), s.get("dep", dep_f.value)
        city_f.value, nights_f.value = s.get("city", city_f.value), s.get("nights", nights_f.value)
        early_f.value = s.get("early", early_f.value)
        state["trip_id"] = tid
        show(1)
        calc_cost()

    def delete_trip(tid):
        store.delete_trip(tid)
        if state["trip_id"] == tid:
            state["trip_id"] = None
        refresh_trips()

    def refresh_trips():
        trips_col.controls.clear()
        trips = store.list_trips()
        if not trips:
            trips_col.controls.append(Note("لا توجد رحلات محفوظة بعد."))
        for t in trips:
            per = t["summary"].get("per")
            sub = f"{t['updated']}" + (f" - للفرد {per:,.0f} دج" if per else "")
            trips_col.controls.append(Card(
                Note(t["name"], GREEN, True, 16), Note(sub, MUTED, size=12),
                ft.Row([Btn("فتح", lambda _, i=t["id"]: load_trip(i)),
                        Btn("نسخة", lambda _, i=t["id"]: (store.duplicate_trip(i), refresh_trips()), False),
                        Btn("حذف", lambda _, i=t["id"]: delete_trip(i), False)], wrap=True)))
        page.update()

    trips_view = ft.Column([trips_col], spacing=12)

    # ---------------- التنقل ----------------
    body = ft.Container(padding=14, expand=True)
    views = [stay_view, cost_view, trips_view]

    def show(i):
        nav.selected_index = i
        scroll = ft.Column([views[i]], scroll=ft.ScrollMode.AUTO, expand=True)
        body.content = scroll
        if i == 2:
            refresh_trips()
        page.update()

    nav = ft.NavigationBar(destinations=[
        ft.NavigationBarDestination(icon=ft.Icons.HOTEL, label="الإقامة"),
        ft.NavigationBarDestination(icon=ft.Icons.CALCULATE, label="التكلفة"),
        ft.NavigationBarDestination(icon=ft.Icons.FOLDER, label="الرحلات")],
        on_change=lambda e: show(int(e.control.selected_index)))

    page.navigation_bar = nav
    page.add(ft.SafeArea(body, expand=True))
    show(0)
    calc_stay()


if __name__ == "__main__":
    (getattr(ft, "run", None) or ft.app)(main)
