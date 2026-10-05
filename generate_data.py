"""สร้างข้อมูลจำลองของบริษัท Voltara (ม.ค. 2024 - ธ.ค. 2025)

รัน:  python3 generate_data.py
ผลลัพธ์: data/*.csv, data/data.js (ให้ index.html ใช้) และ data_dictionary.md
ข้อมูลทั้งหมดเป็นข้อมูลจำลอง ใช้ seed คงที่ รันซ้ำได้ผลเท่าเดิม
"""
import csv
import json
import math
import random
from pathlib import Path

random.seed(67160325)
ROOT = Path(__file__).parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

MONTHS = [f"{y}-{m:02d}" for y in (2024, 2025) for m in range(1, 13)]
GRID_EF = 0.4999  # tCO2/MWh ค่า Grid Emission Factor ของไทย (สมมติฐาน อ้างอิง TGO)
SOLAR_SOURCES = {"solar_farm", "customer_solar"}


def noise(pct):
    return 1 + random.uniform(-pct, pct)


def solar_season(month_idx):
    # ไทย: แดดแรงช่วง มี.ค.-พ.ค. ต่ำช่วงฝน ก.ค.-ก.ย.
    m = month_idx % 12
    return 1 + 0.15 * math.cos((m - 3) * 2 * math.pi / 12)


# ---------- generation.csv (MWh) ----------
# โซลาร์ฟาร์ม: เฟส 1 = 35 MW (2024) ขยายเฟส 2 เป็น 37 MW (2025)
# ผลผลิตต้องอยู่ในช่วงปกติของไทย 1,400–1,500 MWh/MW/ปี (มี assert ตรวจด้านล่าง)
FARM_MW = {"2024": 35, "2025": 37}
YIELD_RANGE = (1400, 1500)
SOLAR_YIELD = 1450        # MWh/MW/ปี ใช้คำนวณไฟจากระบบที่ติดตั้งให้ลูกค้า
CUSTOMER_BASE_KW = 4000   # ระบบลูกค้าที่ติดตั้งไว้ก่อนปี 2024

generation = []
customer_noise = []
for i, month in enumerate(MONTHS):
    s = solar_season(i)
    farm = 4200 * s * (1 + 0.004 * i) * noise(0.04)            # โซลาร์ฟาร์ม (ทยอยเปิดเฟส 2)
    customer_noise.append(noise(0.05))                          # ไฟระบบลูกค้าคำนวณจากยอดติดตั้งทีหลัง
    gas = 2600 * (1.12 if i % 12 in (3, 4, 5) else 1.0) * (1 - 0.006 * i) * noise(0.06)
    for src, mwh in (("solar_farm", farm), ("customer_solar", None), ("gas_plant", gas)):
        generation.append({"month": month, "source": src, "mwh": None if mwh is None else round(mwh, 1)})

# ---------- revenue.csv (ล้านบาท) ----------
gen_by = {(g["month"], g["source"]): g["mwh"] for g in generation}
revenue = []
for i, month in enumerate(MONTHS):
    ppa_mwh = gen_by[(month, "solar_farm")] + gen_by[(month, "gas_plant")]
    ppa = ppa_mwh * 3.6 / 1000 * noise(0.02)                    # ~3.6 บาท/kWh
    install = 21.0 * (1.055 ** i) * noise(0.08)                 # ธุรกิจติดตั้งโต ~5.5%/เดือน
    om = 1.2 * (1.05 ** i) * noise(0.05)                        # สัญญาดูแลระบบลูกค้า
    for seg, v in (("installation", install), ("ppa", ppa), ("om_service", om)):
        revenue.append({"month": month, "segment": seg, "revenue_mthb": round(v, 2)})

# ---------- customers.csv: ลูกค้าติดตั้ง 5 กลุ่ม (ตาม Business Model Canvas) ----------
# segment, ชื่อไทย, ราคาติดตั้ง บาท/W, ขนาดระบบเฉลี่ย kW, สัดส่วนรายได้ติดตั้ง ม.ค.24 → ธ.ค.25
# (government ใช้สัดส่วนเฉลี่ยทั้งปี แล้วกระจุกตามรอบงบประมาณด้านล่าง)
SEGMENTS = [
    ("homeowner", "เจ้าของบ้าน", 38, 5, 0.30, 0.22),
    ("sme", "ร้านค้าและ SMEs", 33, 20, 0.22, 0.22),
    ("small_factory", "โรงงานขนาดเล็ก", 28, 120, 0.22, 0.30),   # ระบบเล็ก-กลาง 50–200 kW
    ("office", "อาคารสำนักงาน", 30, 80, 0.16, 0.16),
    ("government", "หน่วยงานราชการหรือโรงเรียน", 32, 40, 0.10, 0.10),
]
# ปีงบประมาณราชการ ต.ค.–ก.ย. งานติดตั้งกระจุกช่วงเร่งเบิกจ่ายปลายปีงบ (ก.ค.–ก.ย.)
# น้ำหนักเฉลี่ยทั้งปี = 1: ก.ค.–ก.ย. ×2 เดือนอื่น ×2/3
BUDGET_MONTHS = (7, 8, 9)
def gov_weight(month):
    return 2.0 if int(month[5:]) in BUDGET_MONTHS else 2 / 3

monthly_kw = []          # kW ที่ติดตั้งเสร็จแต่ละเดือน (ทุกกลุ่มรวมกัน)
seg_year = {}            # (year, segment) -> {"rev": ล้านบาท, "kw": kW}
customers_monthly = []
for i, month in enumerate(MONTHS):
    t = i / (len(MONTHS) - 1)
    install = next(r["revenue_mthb"] for r in revenue
                   if r["month"] == month and r["segment"] == "installation")
    shares = {seg: s0 + (s1 - s0) * t for seg, _, _, _, s0, s1 in SEGMENTS}
    shares["government"] *= gov_weight(month)
    others = sum(v for k, v in shares.items() if k != "government")
    scale = (1 - shares["government"]) / others                 # รวมทุกกลุ่ม = 100% ของรายได้ติดตั้ง
    kw_month = 0.0
    for seg, _, price, _, _, _ in SEGMENTS:
        share = shares[seg] if seg == "government" else shares[seg] * scale
        rev = install * share
        kw = rev * 1e6 / price / 1000                           # ล้านบาท → kW
        kw_month += kw
        acc = seg_year.setdefault((month[:4], seg), {"rev": 0.0, "kw": 0.0})
        acc["rev"] += rev
        acc["kw"] += kw
        customers_monthly.append({"month": month, "segment": seg,
                                  "revenue_mthb": round(rev, 2), "kw_installed": round(kw, 1)})
    monthly_kw.append(kw_month)

customers = []
for y in ("2024", "2025"):
    for seg, name, price, size, _, _ in SEGMENTS:
        acc = seg_year[(y, seg)]
        customers.append({
            "year": y, "segment": seg, "segment_th": name,
            "projects": round(acc["kw"] / size), "kw_installed": round(acc["kw"]),
            "avg_system_kw": size, "price_thb_per_w": price,
            "revenue_mthb": round(acc["rev"], 2),
        })

# ไฟจากระบบลูกค้า = กำลังผลิตสะสม (ติดตั้งเสร็จเดือนก่อนหน้า) × ผลผลิตต่อ MW
fleet_kw = CUSTOMER_BASE_KW
for i, g in enumerate(r for r in generation if r["source"] == "customer_solar"):
    g["mwh"] = round(fleet_kw / 1000 * SOLAR_YIELD / 12 * solar_season(i) * customer_noise[i], 1)
    fleet_kw += monthly_kw[i]
CUSTOMER_FLEET_END_KW = fleet_kw

# ---------- co2_reduction.csv (นับเฉพาะไฟจากโซลาร์) ----------
co2 = [
    {
        "month": g["month"],
        "source": g["source"],
        "solar_mwh": g["mwh"],
        "grid_ef_tco2_per_mwh": GRID_EF,
        "tco2_avoided": round(g["mwh"] * GRID_EF, 1),
    }
    for g in generation
    if g["source"] in SOLAR_SOURCES
]
assert all(r["source"] in SOLAR_SOURCES for r in co2), "co2_reduction ต้องไม่มีไฟจากก๊าซ"

# ตรวจว่าขนาดโซลาร์ฟาร์มสอดคล้องกับไฟที่ผลิต
FARM_YIELD = {}
for y, mw in FARM_MW.items():
    mwh = sum(g["mwh"] for g in generation if g["source"] == "solar_farm" and g["month"].startswith(y))
    FARM_YIELD[y] = mwh / mw
    assert YIELD_RANGE[0] <= FARM_YIELD[y] <= YIELD_RANGE[1], f"ผลผลิตฟาร์มปี {y} = {FARM_YIELD[y]:.0f} MWh/MW"

# ---------- household_bill.csv: ค่าไฟครัวเรือน (บทที่ 1 ปัญหา) ----------
# ค่าไฟเฉลี่ยบ้านอยู่อาศัยรวม Ft (บาท/หน่วย ก่อน VAT) รายงวด 4 เดือน
# ค่าประมาณอิงประกาศ กกพ. ควรตรวจกับแหล่งจริงก่อนอ้างอิงในรายงาน
TARIFF = [
    ("2022 ม.ค.-เม.ย.", 3.78), ("2022 พ.ค.-ส.ค.", 4.00), ("2022 ก.ย.-ธ.ค.", 4.72),
    ("2023 ม.ค.-เม.ย.", 4.72), ("2023 พ.ค.-ส.ค.", 4.70), ("2023 ก.ย.-ธ.ค.", 3.99),
    ("2024 ม.ค.-เม.ย.", 4.18), ("2024 พ.ค.-ส.ค.", 4.18), ("2024 ก.ย.-ธ.ค.", 4.18),
    ("2025 ม.ค.-เม.ย.", 4.15), ("2025 พ.ค.-ส.ค.", 3.98), ("2025 ก.ย.-ธ.ค.", 3.98),
]
HOME_KWH = 400            # บ้านทั่วไปใช้ไฟ 400 หน่วย/เดือน
SOLAR_OFFSET_KWH = 200    # ระบบ 5 kW ใช้เองตอนกลางวันได้ราว 200 หน่วย/เดือน
VAT = 1.07
household_bill = [
    {"period": p, "tariff_thb_per_kwh": t,
     "bill_400kwh_thb": round(HOME_KWH * t * VAT),
     "bill_with_5kw_solar_thb": round((HOME_KWH - SOLAR_OFFSET_KWH) * t * VAT)}
    for p, t in TARIFF
]

# ---------- costs.csv (ล้านบาท) จัดหมวดตาม 4M ----------
COSTS = [
    # category, 4M, ผู้เกี่ยวข้อง (Key Partner)
    ("gas_fuel", "Material", "ผู้จัดหาก๊าซธรรมชาติ"),
    ("solar_equipment", "Material", "ผู้ผลิตแผง/อินเวอร์เตอร์"),
    ("labor", "Man", "ทีมติดตั้งและวิศวกร"),
    ("maintenance", "Machine", "ผู้รับเหมา O&M"),
    ("admin_process", "Method", "ภายในบริษัท"),
]
rev_by = {(r["month"], r["segment"]): r["revenue_mthb"] for r in revenue}
costs = []
for i, month in enumerate(MONTHS):
    install = rev_by[(month, "installation")]
    gas_mwh = gen_by[(month, "gas_plant")]
    values = {
        "gas_fuel": gas_mwh * 2.45 / 1000 * noise(0.05),        # ~2.45 บาท/kWh
        "solar_equipment": install * 0.52 * noise(0.04),
        "labor": (2.8 + install * 0.12) * noise(0.03),
        "maintenance": 1.6 * (1.01 ** i) * noise(0.08),
        "admin_process": 2.2 * noise(0.05),
    }
    for cat, m4, partner in COSTS:
        costs.append({"month": month, "category": cat, "m4": m4,
                      "key_partner": partner, "cost_mthb": round(values[cat], 2)})


def write_csv(name, rows):
    with open(DATA / name, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


write_csv("generation.csv", generation)
write_csv("co2_reduction.csv", co2)
write_csv("revenue.csv", revenue)
write_csv("costs.csv", costs)
write_csv("customers.csv", customers)
write_csv("customers_monthly.csv", customers_monthly)
write_csv("household_bill.csv", household_bill)

# data.js ให้ index.html เปิดได้ตรง ๆ แบบ file:// (fetch CSV ใช้ไม่ได้ใน file://)
payload = {"months": MONTHS, "generation": generation, "co2": co2,
           "revenue": revenue, "costs": costs, "grid_ef": GRID_EF,
           "customers": customers, "customers_monthly": customers_monthly,
           "budget_months": list(BUDGET_MONTHS), "household_bill": household_bill,
           "farm_mw": FARM_MW, "farm_yield": {y: round(v) for y, v in FARM_YIELD.items()},
           "customer_fleet_end_mw": round(CUSTOMER_FLEET_END_KW / 1000, 1)}
(DATA / "data.js").write_text(
    "// สร้างโดย generate_data.py ห้ามแก้มือ\nwindow.VOLTARA = "
    + json.dumps(payload, ensure_ascii=False) + ";\n", encoding="utf-8")

# ---------- สรุปตัวเลขสำหรับ data_dictionary.md ----------
def total(rows, key, **flt):
    return sum(r[key] for r in rows if all(r[k] == v for k, v in flt.items()))


def year_total(rows, key, year, **flt):
    return sum(r[key] for r in rows if r["month"].startswith(year)
               and all(r[k] == v for k, v in flt.items()))


S = {}
for y in ("2024", "2025"):
    S[f"inst_{y}"] = year_total(revenue, "revenue_mthb", y, segment="installation")
    S[f"ppa_{y}"] = year_total(revenue, "revenue_mthb", y, segment="ppa")
    S[f"om_{y}"] = year_total(revenue, "revenue_mthb", y, segment="om_service")
    S[f"rev_{y}"] = year_total(revenue, "revenue_mthb", y)
    S[f"co2_{y}"] = year_total(co2, "tco2_avoided", y)
    S[f"gasfuel_{y}"] = year_total(costs, "cost_mthb", y, category="gas_fuel")
S["inst_growth"] = S["inst_2025"] / S["inst_2024"] - 1
S["ppa_growth"] = S["ppa_2025"] / S["ppa_2024"] - 1
S["co2_total"] = total(co2, "tco2_avoided")
S["co2_farm"] = total(co2, "tco2_avoided", source="solar_farm")
S["co2_cust"] = total(co2, "tco2_avoided", source="customer_solar")
S["solar_mwh"] = total(co2, "solar_mwh")
S["gas_mwh"] = total(generation, "mwh", source="gas_plant")
S["cost_total"] = total(costs, "cost_mthb")
S["gasfuel_total"] = total(costs, "cost_mthb", category="gas_fuel")


def f(x, d=1):
    return f"{x:,.{d}f}"


def pct(x):
    return f"{x * 100:+.1f}%"


cust = {(c["year"], c["segment"]): c for c in customers}
inst_increase = S["inst_2025"] - S["inst_2024"]
seg_rows = "\n".join(
    f"| {name} | {cust[('2024', seg)]['projects']:,} → {cust[('2025', seg)]['projects']:,} "
    f"| {cust[('2024', seg)]['kw_installed']:,} → {cust[('2025', seg)]['kw_installed']:,} "
    f"| {f(cust[('2024', seg)]['revenue_mthb'])} → {f(cust[('2025', seg)]['revenue_mthb'])} "
    f"| {(cust[('2025', seg)]['revenue_mthb'] - cust[('2024', seg)]['revenue_mthb']) / inst_increase * 100:.0f}% |"
    for seg, name, *_ in SEGMENTS)
def _top():
    best = None
    for seg, name, price, size, *_ in SEGMENTS:
        a, b = cust[("2024", seg)], cust[("2025", seg)]
        share = (b["revenue_mthb"] - a["revenue_mthb"]) / inst_increase * 100
        if best is None or share > best["share"]:
            best = {"name": name, "a": a["revenue_mthb"], "b": b["revenue_mthb"], "share": share,
                    "size": size, "value": size * price / 1000, "pa": a["projects"], "pb": b["projects"]}
    return best


TOP = _top()
gov_rows = [r for r in customers_monthly if r["segment"] == "government"]
GOV_PEAK = sum(r["revenue_mthb"] for r in gov_rows if int(r["month"][5:]) in BUDGET_MONTHS) / sum(
    r["revenue_mthb"] for r in gov_rows) * 100
bill_rows = "\n".join(
    f"| {b['period']} | {b['tariff_thb_per_kwh']:.2f} | {b['bill_400kwh_thb']:,} | {b['bill_with_5kw_solar_thb']:,} |"
    for b in household_bill)


md = f"""# Data Dictionary — Voltara Dashboard

> ข้อมูลจำลองทั้งหมด สร้างจาก `generate_data.py` (seed = 67160325) ช่วง ม.ค. 2024 – ธ.ค. 2025 รายเดือน
> แก้ข้อมูลให้แก้ที่สคริปต์แล้วรันใหม่ ห้ามแก้ CSV ด้วยมือ ตัวเลขในไฟล์นี้สร้างอัตโนมัติ

ผู้จัดทำ: ชลธี กิมสร้อย 67160325

## 1. `data/generation.csv` — ปริมาณไฟฟ้าที่ผลิต

| คอลัมน์ | ชนิด | หน่วย | ความหมาย |
|---|---|---|---|
| month | text | YYYY-MM | เดือน |
| source | text | — | `solar_farm` โซลาร์ฟาร์มของบริษัท · `customer_solar` ระบบที่ติดตั้งให้ลูกค้า · `gas_plant` โรงไฟฟ้าก๊าซ |
| mwh | number | MWh | ไฟฟ้าที่ผลิตได้ในเดือนนั้น |

## 2. `data/co2_reduction.csv` — CO₂ ที่ลดได้ (นับเฉพาะไฟจากโซลาร์)

| คอลัมน์ | ชนิด | หน่วย | ความหมาย |
|---|---|---|---|
| month | text | YYYY-MM | เดือน |
| source | text | — | มีเฉพาะ `solar_farm` และ `customer_solar` |
| solar_mwh | number | MWh | ไฟจากโซลาร์ (ตรงกับ generation.csv) |
| grid_ef_tco2_per_mwh | number | tCO₂/MWh | ค่า Grid Emission Factor = {GRID_EF} (สมมติฐาน อิงค่าของ TGO) |
| tco2_avoided | number | tCO₂ | solar_mwh × grid_ef |

**กฎการนับ:** ไฟจากโรงไฟฟ้าก๊าซ (`gas_plant`) ไม่ถูกนับเป็นการลด CO₂ เพราะเป็นการเผาเชื้อเพลิงฟอสซิล
สคริปต์มี `assert` ป้องกันไม่ให้แถว gas หลุดเข้าไฟล์นี้

| ตัวเลข | ค่า |
|---|---|
| ไฟจากโซลาร์รวม 24 เดือน | {f(S['solar_mwh'], 0)} MWh |
| ไฟจากก๊าซ (ไม่นับ) | {f(S['gas_mwh'], 0)} MWh |
| CO₂ ที่ลดได้รวม | **{f(S['co2_total'], 0)} tCO₂** |
| — จากโซลาร์ฟาร์ม | {f(S['co2_farm'], 0)} tCO₂ |
| — จากระบบที่ติดตั้งให้ลูกค้า | {f(S['co2_cust'], 0)} tCO₂ |
| CO₂ ที่ลดได้ ปี 2024 → 2025 | {f(S['co2_2024'], 0)} → {f(S['co2_2025'], 0)} tCO₂ ({pct(S['co2_2025'] / S['co2_2024'] - 1)}) |

**ตรวจความสอดคล้องขนาดโซลาร์ฟาร์ม** (ช่วงปกติของไทย {YIELD_RANGE[0]:,}–{YIELD_RANGE[1]:,} MWh/MW/ปี)

| ปี | กำลังผลิต | ไฟที่ผลิต | ผลผลิตต่อ MW |
|---|---|---|---|
| 2024 | {FARM_MW['2024']} MW (เฟส 1) | {f(FARM_YIELD['2024'] * FARM_MW['2024'], 0)} MWh | {f(FARM_YIELD['2024'], 0)} MWh/MW ✓ |
| 2025 | {FARM_MW['2025']} MW (ขยายเฟส 2) | {f(FARM_YIELD['2025'] * FARM_MW['2025'], 0)} MWh | {f(FARM_YIELD['2025'], 0)} MWh/MW ✓ |

ระบบที่ติดตั้งให้ลูกค้า: เริ่มต้น {CUSTOMER_BASE_KW / 1000:.0f} MW + ยอดติดตั้งใน `customers.csv` รวมเป็น {CUSTOMER_FLEET_END_KW / 1000:.1f} MW ณ สิ้นปี 2025
ผลิตไฟเดือนละ กำลังผลิตสะสม × {SOLAR_YIELD:,}/12 MWh/MW (ปรับตามฤดู)

## 3. `data/revenue.csv` — รายได้

| คอลัมน์ | ชนิด | หน่วย | ความหมาย |
|---|---|---|---|
| month | text | YYYY-MM | เดือน |
| segment | text | — | `installation` รายได้ติดตั้งโซลาร์ให้ลูกค้า · `ppa` ขายไฟตามสัญญา PPA (โซลาร์ฟาร์ม + ก๊าซ) · `om_service` สัญญาดูแลระบบ |
| revenue_mthb | number | ล้านบาท | รายได้ |

| ตัวเลข | 2024 | 2025 | เติบโต |
|---|---|---|---|
| รายได้ติดตั้ง | {f(S['inst_2024'])} | {f(S['inst_2025'])} | **{pct(S['inst_growth'])}** |
| รายได้ PPA | {f(S['ppa_2024'])} | {f(S['ppa_2025'])} | {pct(S['ppa_growth'])} |
| รายได้ O&M | {f(S['om_2024'])} | {f(S['om_2025'])} | {pct(S['om_2025'] / S['om_2024'] - 1)} |
| รวม | {f(S['rev_2024'])} | {f(S['rev_2025'])} | {pct(S['rev_2025'] / S['rev_2024'] - 1)} |
| สัดส่วนรายได้ติดตั้ง | {S['inst_2024'] / S['rev_2024'] * 100:.1f}% | {S['inst_2025'] / S['rev_2025'] * 100:.1f}% | |

**ใช้ในบทที่ 5:** รายได้ติดตั้งมากกว่า PPA และโตเร็วกว่า ({pct(S['inst_growth'])} เทียบกับ {pct(S['ppa_growth'])})
หมายความว่าธุรกิจบริการโตเร็วกว่าการขายไฟ

**เหตุผลที่รายได้ติดตั้งโต {pct(S['inst_growth'])}:** กลุ่ม{TOP['name']}เป็นแรงขับหลัก
รายได้เพิ่มจาก {f(TOP['a'])} เป็น {f(TOP['b'])} ล้านบาท
คิดเป็น {TOP['share']:.0f}% ของรายได้ติดตั้งที่เพิ่มขึ้นทั้งหมด
ระบบเฉลี่ย {TOP['size']} kW โครงการละราว {f(TOP['value'])} ล้านบาท และจำนวนโครงการเพิ่มจาก {TOP['pa']} เป็น {TOP['pb']} (รายละเอียดในหัวข้อ 5)

## 4. `data/costs.csv` — ต้นทุนจัดหมวดตาม 4M

| คอลัมน์ | ชนิด | หน่วย | ความหมาย |
|---|---|---|---|
| month | text | YYYY-MM | เดือน |
| category | text | — | `gas_fuel` ค่าเชื้อเพลิงก๊าซ · `solar_equipment` แผง/อินเวอร์เตอร์ · `labor` ค่าแรง · `maintenance` ซ่อมบำรุง · `admin_process` บริหาร/กระบวนการ |
| m4 | text | — | หมวด 4M: Man / Machine / Material / Method |
| key_partner | text | — | คู่ค้าหลักใน Business Model Canvas ที่เกี่ยวข้อง |
| cost_mthb | number | ล้านบาท | ต้นทุน |

| ตัวเลข | ค่า |
|---|---|
| ต้นทุนรวม 24 เดือน | {f(S['cost_total'])} ล้านบาท |
| ค่าเชื้อเพลิงก๊าซ (Material / ผู้จัดหาก๊าซ) | {f(S['gasfuel_total'])} ล้านบาท ({S['gasfuel_total'] / S['cost_total'] * 100:.1f}% ของต้นทุน) |
| ค่าเชื้อเพลิงก๊าซ ปี 2024 → 2025 | {f(S['gasfuel_2024'])} → {f(S['gasfuel_2025'])} ล้านบาท |

## 5. `data/customers.csv` — ลูกค้าติดตั้ง 5 กลุ่ม (บทที่ 2 ลูกค้า)

| คอลัมน์ | ชนิด | หน่วย | ความหมาย |
|---|---|---|---|
| year | text | YYYY | ปี |
| segment | text | — | `homeowner` เจ้าของบ้าน · `sme` ร้านค้าและ SMEs · `small_factory` โรงงานขนาดเล็ก (ระบบ 50–200 kW) · `office` อาคารสำนักงาน · `government` หน่วยงานราชการหรือโรงเรียน |
| segment_th | text | — | ชื่อกลุ่มภาษาไทย |
| projects | number | โครงการ | จำนวนโครงการที่ติดตั้ง (kw_installed ÷ avg_system_kw) |
| kw_installed | number | kW | กำลังผลิตที่ติดตั้งในปีนั้น |
| avg_system_kw | number | kW | ขนาดระบบเฉลี่ยต่อโครงการ |
| price_thb_per_w | number | บาท/W | ราคาติดตั้งเฉลี่ย (ระบบใหญ่ถูกกว่าต่อวัตต์) |
| revenue_mthb | number | ล้านบาท | รายได้ติดตั้ง รวมทุกกลุ่มเท่ากับ `installation` ใน revenue.csv |

| กลุ่ม | โครงการ 2024 → 2025 | kW 2024 → 2025 | รายได้ (ล้านบาท) | สัดส่วนของรายได้ที่เพิ่มขึ้น |
|---|---|---|---|---|
{seg_rows}

**ราชการ/โรงเรียนกระจุกตามรอบงบประมาณ:** ปีงบประมาณเริ่ม ต.ค. งานติดตั้งจึงกระจุกช่วงเร่งเบิกจ่ายปลายปีงบ (ก.ค.–ก.ย.)
รายได้กลุ่มนี้ {GOV_PEAK:.0f}% อยู่ใน 3 เดือนดังกล่าว ดูรายเดือนได้ใน `data/customers_monthly.csv`
(คอลัมน์ month, segment, revenue_mthb, kw_installed)

## 6. `data/household_bill.csv` — ค่าไฟครัวเรือน (บทที่ 1 ปัญหา)

| คอลัมน์ | ชนิด | หน่วย | ความหมาย |
|---|---|---|---|
| period | text | — | งวดค่าไฟ 4 เดือน |
| tariff_thb_per_kwh | number | บาท/หน่วย | ค่าไฟเฉลี่ยบ้านอยู่อาศัยรวม Ft ก่อน VAT (**ค่าประมาณ ควรตรวจกับประกาศ กกพ.**) |
| bill_400kwh_thb | number | บาท/เดือน | บิลบ้านที่ใช้ไฟ {HOME_KWH} หน่วย/เดือน รวม VAT 7% |
| bill_with_5kw_solar_thb | number | บาท/เดือน | บิลหลังติดโซลาร์ 5 kW (ใช้เองกลางวันได้ราว {SOLAR_OFFSET_KWH} หน่วย) |

| งวด | ค่าไฟ (บาท/หน่วย) | บิล 400 หน่วย | บิลหลังติดโซลาร์ |
|---|---|---|---|
{bill_rows}
"""
(ROOT / "data_dictionary.md").write_text(md, encoding="utf-8")
print(md)
