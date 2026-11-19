# -*- coding: utf-8 -*-
"""
NormAI — ҚР сәулет-құрылыс нормаларын (ҚНжЕ / ҚР ЕЖ) тексеруге арналған ЖИ-ассистент.
Команда: ArchiCore (АЖиОЗ 25-4)

Архитектура (RAG-пайплайн):
    1. Retriever  — retrieve_norms(): кілт сөздер бойынша ішкі нормативтік базадан үзінділер табады.
    2. Generator  — Gemini (gemini-2.5-flash) табылған нормаларды контекст ретінде алып жауап береді.
    3. Fallback   — analyze_locally(): API кілтсіз жұмыс істейтін ереже негізіндегі жергілікті тексеру.

Ескерту: ішкі база оқу мақсатында қысқаша жинақталған. Нақты жобалау кезінде
нормативтік құжаттардың ресми әрі қолданыстағы басылымын тексеріңіз.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, fields
from typing import Dict, List, Optional

import streamlit as st

try:  # Google Gen AI SDK (pip install google-genai)
    from google import genai
    from google.genai import types

    GENAI_AVAILABLE = True
except Exception:  # pragma: no cover
    GENAI_AVAILABLE = False


# =============================================================================
# 0. ҚОСЫМША БАПТАУЛАР
# =============================================================================
APP_TITLE = "NormAI"
APP_SUBTITLE = "ҚР сәулет-құрылыс нормаларын (ҚНжЕ / ҚР ЕЖ) тексеруге арналған ЖИ-ассистент"
MODEL_NAME = "gemini-2.5-flash"

MODE_API = "ЖИ-талдау (API арқылы)"
MODE_DEMO = "Демо-режим (API кілтсіз тексеру)"

DEGREES = ["Көрсетілмеген", "I", "II", "III", "IV", "V"]
DIRECTIONS = [
    "Көрсетілмеген",
    "Солтүстік",
    "Оңтүстік",
    "Шығыс",
    "Батыс",
    "Солтүстік-шығыс",
    "Солтүстік-батыс",
    "Оңтүстік-шығыс",
    "Оңтүстік-батыс",
]

EXAMPLES = {
    "fire": {
        "label": "🔥 Өртке қарсы арақашықтық",
        "text": (
            "9 қабатты тұрғын үй (II дәрежелі отқа төзімділік) мен көрші 3 қабатты "
            "қоғамдық ғимарат (III дәрежелі) арасындағы арақашықтық 6 м. "
            "Өртке қарсы арақашықтық талаптарына сәйкес келе ме?"
        ),
    },
    "insolation": {
        "label": "☀️ Тұрғын үй инсоляциясы",
        "text": (
            "Алматыдағы тұрғын үйдің бір бөлмелі пәтерінің терезесі солтүстікке қараған. "
            "Инсоляция ұзақтығы 1,5 сағат. Нормаға сәйкес келе ме?"
        ),
    },
    "evacuation": {
        "label": "🚪 Эвакуация жолдарының ені",
        "text": (
            "Кеңсе ғимаратының эвакуациялық дәлізінің ені 1,0 м, эвакуациялық есіктің "
            "ені 0,8 м. Ғимарат 5 қабатты. Талаптарға сәйкес келе ме?"
        ),
    },
}


# =============================================================================
# 1. БАЗА ЗНАНИЙ (нормативтік база)
# =============================================================================
NORMS: List[Dict] = [
    {
        "id": "fire_distance",
        "topic": "Ғимараттар арасындағы өртке қарсы арақашықтық",
        "doc": "ҚР ҚН 2.02-01-2023",
        "clause": "Ғимараттар мен құрылыстар арасындағы өртке қарсы ара қашықтықтар (кесте)",
        "text": (
            "Ғимараттар арасындағы өртке қарсы арақашықтық олардың отқа төзімділік "
            "дәрежесіне байланысты 6 м-ден 15 м-ге дейін қабылданады: "
            "I–II және I–II — 6 м; I–II және III — 8 м; III және III — 8 м; "
            "I–II және IV–V — 10 м; III және IV–V — 10 м; IV–V және IV–V — 15 м. "
            "Арақашықтықты азайту үшін өртке қарсы қабырға (брандмауэр) және басқа "
            "нормада қарастырылған шаралар қолданылуы мүмкін."
        ),
        "keywords": [
            "өрт", "өртке қарсы", "отқа төзімділік", "арақашықтық", "ара қашықтық",
            "көрші ғимарат", "брандмауэр", "пожар", "противопожар", "огнестойк",
            "разрыв", "расстояние между",
        ],
    },
    {
        "id": "insolation",
        "topic": "Тұрғын бөлмелердің инсоляциясы",
        "doc": "ҚР ЕЖ 3.01-101-2013 және тұрғын үйге қойылатын санитарлық талаптар",
        "clause": "Тұрғын үй мен аумақтың инсоляциясы",
        "text": (
            "Тұрғын бөлмелердің үздіксіз инсоляция ұзақтығы ҚР оңтүстік және орталық "
            "аймақтары үшін кемінде 2,5 сағат болуы тиіс. Терезелері тек солтүстікке "
            "бағытталған пәтерлерді жобалауға жол берілмейді; солтүстік-шығыс және "
            "солтүстік-батыс бағыттарда инсоляциялық есеп міндетті."
        ),
        "keywords": [
            "инсоляц", "күн сәулесі", "күн сәуле", "солтүстік", "оңтүстік", "бағыт",
            "табиғи жарық", "жарықтандыру", "ориентац", "инсол", "солнечн",
        ],
    },
    {
        "id": "evacuation",
        "topic": "Эвакуациялық жолдар мен шығыстардың ені",
        "doc": "ҚР ҚН 2.02-01-2023",
        "clause": "Эвакуациялық жолдар және эвакуациялық шығыстар",
        "text": (
            "Эвакуациялық жолдардың (дәліздердің) ені кемінде 1,2 м болуы тиіс; "
            "эвакуацияланатын адам саны көп болған жағдайда ені есеппен ұлғайтылады. "
            "Эвакуациялық шығыс есіктерінің жарықтағы ені кемінде 0,8 м. "
            "Жол бойында ені мен биіктігін азайтатын бөгеттер болмауы тиіс."
        ),
        "keywords": [
            "эвакуац", "дәліз", "коридор", "эвакуациялық шығыс", "есік", "қашу жол",
            "эвакуаци", "дверь", "путь эвакуации",
        ],
    },
    {
        "id": "ceiling_height",
        "topic": "Тұрғын үй қабатының биіктігі",
        "doc": "ҚР ЕЖ 3.02-101-2012",
        "clause": "Көппәтерлі тұрғын үйлердің үй-жайларына қойылатын талаптар",
        "text": (
            "Тұрғын бөлмелер мен асүйдің еден мен төбе арасындағы биіктігі "
            "(жарықтағы) кемінде 2,7 м болуы тиіс."
        ),
        "keywords": [
            "биік", "төбе", "еден мен төбе", "қабат биіктігі", "потолок",
            "высота этаж", "высота помещ", "жарықтағы",
        ],
    },
    {
        "id": "parking",
        "topic": "Автотұрақтардан тұрғын үй терезелеріне дейінгі арақашықтық",
        "doc": "ҚР ЕЖ 3.01-101-2013 және санитарлық қорғау талаптары",
        "clause": "Автотұрақтарды орналастыру, санитарлық үзіліс",
        "text": (
            "Ашық автотұрақтардан тұрғын үйлердің терезелеріне дейінгі арақашықтық "
            "тұрақтағы көлік санына байланысты кемінде 10–15 м: 10 көлікке дейін — 10 м, "
            "11–50 көлік — 15 м. Көлік саны артқан сайын арақашықтық ұлғаяды (50-ден "
            "көп болса — 25 м және одан артық, нақтылау қажет)."
        ),
        "keywords": [
            "тұрақ", "автотұрақ", "парковк", "стоянк", "көлік", "машина",
            "автомобиль", "терезеге дейін",
        ],
    },
    {
        "id": "fire_access",
        "topic": "Өрт сөндіру техникасының өтуі",
        "doc": "ҚР ҚН 2.02-01-2023",
        "clause": "Өрт сөндіру көліктеріне арналған өтпелер мен кіреберістер",
        "text": (
            "Өрт сөндіру көліктерінің өтпе жолының ені кемінде 3,5 м; биіктігі 13 м-ден "
            "асатын (шамамен 4 қабаттан жоғары) ғимараттарға өтпе ені кемінде 4,2 м "
            "болуы тиіс. Биік және көпқабатты ғимараттарға қосымша талаптар қойылады."
        ),
        "keywords": [
            "өрт сөндіру", "өтпе", "өту жолы", "проезд", "подъезд", "өрт көлігі",
            "көпқабатты", "биік ғимарат", "жол ені", "пожарн",
        ],
    },
]

NORMS_BY_ID = {n["id"]: n for n in NORMS}

SIDEBAR_DOCS = [
    ("ҚР ЕЖ 3.01-101-2013", "Қалалық және ауылдық елді мекендерді жоспарлау және салу"),
    ("ҚР ҚН 2.02-01-2023", "Ғимараттар мен құрылыстардың өрт қауіпсіздігі"),
    ("ҚР ЕЖ 3.02-101-2012", "Көппәтерлі тұрғын үйлер"),
    ("Санитарлық талаптар", "Тұрғын үй-жайлардың инсоляциясы мен санитарлық үзілістер"),
]


# =============================================================================
# 2. ПАРАМЕТРЛЕР ЖӘНЕ МӘТІННЕН ШЫҒАРЫП АЛУ
# =============================================================================
@dataclass
class Params:
    floors: int = 0
    neighbor_distance: float = 0.0
    orientation: str = ""
    own_degree: str = ""
    neighbor_degree: str = ""
    corridor_width: float = 0.0
    door_width: float = 0.0
    floor_height: float = 0.0
    parking_distance: float = 0.0
    parking_cars: int = 0
    insolation_hours: float = 0.0
    driveway_width: float = 0.0


PARAM_LABELS = {
    "floors": "Қабаттылығы",
    "neighbor_distance": "Көрші ғимаратқа дейінгі арақашықтық, м",
    "orientation": "Терезе бағыты",
    "own_degree": "Ғимараттың отқа төзімділік дәрежесі",
    "neighbor_degree": "Көрші ғимараттың отқа төзімділік дәрежесі",
    "corridor_width": "Эвакуациялық дәліз ені, м",
    "door_width": "Эвакуациялық есік ені, м",
    "floor_height": "Қабат биіктігі (жарықтағы), м",
    "parking_distance": "Автотұрақтан терезеге дейінгі арақашықтық, м",
    "parking_cars": "Тұрақтағы көлік саны",
    "insolation_hours": "Инсоляция ұзақтығы, сағ",
    "driveway_width": "Өрт сөндіру өтпесінің ені, м",
}

NUM_UNIT_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(сағат\w*|сағ\b|час\w*|ч\b|метр\w*|м\b|m\b)", re.IGNORECASE
)
FLOORS_RE = re.compile(r"(\d+)\s*[-–]?\s*(?:қабатты|қабат|этажн\w*|этаж)")
CARS_RE = re.compile(r"(\d+)\s*(?:автокөлік|көлік|машина|автомобиль)")

CATEGORY_KEYS = {
    "parking": ["тұрақ", "автотұр", "парковк", "стоянк"],
    "corridor": ["дәліз", "коридор"],
    "door": ["есік", "дверь", "эвакуациялық шығыс", "шығыс есі"],
    "height": ["биік", "высот", "төбе"],
    "driveway": ["өтпе", "өту жолы", "проезд", "подъезд", "өрт сөндіру"],
    "distance": ["арақашықтық", "ара қашықтық", "қашықтық", "аралық", "расстоя", "разрыв"],
}
CATEGORY_FIELD = {
    "distance": "neighbor_distance",
    "parking": "parking_distance",
    "corridor": "corridor_width",
    "door": "door_width",
    "height": "floor_height",
    "driveway": "driveway_width",
}
ORIENTATION_PATTERNS = [
    ("Солтүстік-шығыс", r"солтүстік[\s-]*шығыс"),
    ("Солтүстік-батыс", r"солтүстік[\s-]*батыс"),
    ("Оңтүстік-шығыс", r"оңтүстік[\s-]*шығыс"),
    ("Оңтүстік-батыс", r"оңтүстік[\s-]*батыс"),
    ("Солтүстік", r"солтүстік|север"),
    ("Оңтүстік", r"оңтүстік|\bюг|южн"),
    ("Шығыс", r"шығысқа|шығыс\s+бағыт|восточн"),
    ("Батыс", r"батысқа|батыс\s+бағыт|западн"),
]


def _to_float(value: str) -> float:
    return float(value.replace(",", "."))


def _classify(segment: str, unit: str) -> Optional[str]:
    """Санның қандай параметрге жататынын жақын кілт сөз бойынша анықтайды."""
    if unit.lower().startswith(("сағ", "час", "ч")):
        return "hours"
    seg = segment.lower()
    best, best_pos = None, -1
    for category, keys in CATEGORY_KEYS.items():
        for key in keys:
            pos = seg.rfind(key)
            if pos > best_pos:
                best, best_pos = category, pos
    if best == "distance" and any(k in seg for k in CATEGORY_KEYS["parking"]):
        best = "parking"
    return best


def extract_from_text(text: str) -> Params:
    """Еркін мәтіннен сандық параметрлерді (ені, арақашықтық, сағат т.б.) шығарады."""
    p = Params()
    low = text.lower()

    m = FLOORS_RE.search(low)
    if m:
        p.floors = int(m.group(1))
    m = CARS_RE.search(low)
    if m:
        p.parking_cars = int(m.group(1))

    prev_end = 0
    for m in NUM_UNIT_RE.finditer(low):
        value = _to_float(m.group(1))
        unit = m.group(2)
        segment = low[prev_end:m.start()]
        prev_end = m.end()
        category = _classify(segment, unit)
        if category is None:
            category = _classify(low[m.end():m.end() + 30], unit)
        if category == "hours":
            if not p.insolation_hours:
                p.insolation_hours = value
        elif category in CATEGORY_FIELD:
            attr = CATEGORY_FIELD[category]
            if not getattr(p, attr):
                setattr(p, attr, value)

    if re.search(r"терез|бағыт|қараған|қарайды|фасад|окн|ориентац", low):
        for label, pattern in ORIENTATION_PATTERNS:
            if re.search(pattern, low):
                p.orientation = label
                break

    roman = re.findall(r"\b(IV|V|I{1,3})\s*[-–]?\s*(?:дәреж|степен)", text.replace("І", "I"))
    if len(roman) >= 2:
        p.own_degree, p.neighbor_degree = roman[0], roman[1]
    elif len(roman) == 1:
        p.own_degree = roman[0]
        if re.search(r"екі\s+ғимарат\s+та|екеуі\s+де|екеуінің\s+де|\bобе\b|\bоба\b", low):
            p.neighbor_degree = roman[0]
    return p


def merge_params(form: Params, extracted: Params) -> Params:
    """Форма мәндері басым; бос өрістер мәтіннен толтырылады."""
    merged = Params()
    for f in fields(Params):
        form_value = getattr(form, f.name)
        setattr(merged, f.name, form_value if form_value else getattr(extracted, f.name))
    return merged


def params_to_lines(p: Params) -> List[str]:
    lines = []
    for f in fields(Params):
        value = getattr(p, f.name)
        if value:
            shown = fmt(value) if isinstance(value, float) else value
            lines.append(f"{PARAM_LABELS[f.name]}: {shown}")
    return lines


def fmt(x) -> str:
    """2.5 -> '2,5'; 6.0 -> '6'."""
    if isinstance(x, float):
        return f"{x:g}".replace(".", ",")
    return str(x)


def implied_topics(p: Params) -> set:
    """Берілген параметрлерге қарай қандай нормалар қажет екенін анықтайды."""
    topics = set()
    if p.neighbor_distance or p.own_degree or p.neighbor_degree:
        topics.add("fire_distance")
    if p.insolation_hours or p.orientation:
        topics.add("insolation")
    if p.corridor_width or p.door_width:
        topics.add("evacuation")
    if p.floor_height:
        topics.add("ceiling_height")
    if p.parking_distance or p.parking_cars:
        topics.add("parking")
    if p.driveway_width:
        topics.add("fire_access")
    return topics


# =============================================================================
# 3. RETRIEVER
# =============================================================================
def retrieve_norms(query: str, hints: Optional[set] = None, top_k: int = 4) -> List[Dict]:
    """
    Сұраудағы кілт сөздер бойынша ішкі нормативтік базадан ең өзекті
    пункттерді табады. Қайтарады: [{**норма, 'score': int, 'matched': [..]}, ...]
    hints — параметрлерден шығатын тақырыптар (қосымша салмақ береді).
    """
    q = (query or "").lower()
    hints = hints or set()
    scored = []
    for norm in NORMS:
        matched = [kw for kw in norm["keywords"] if kw in q]
        score = len(matched) + (3 if norm["id"] in hints else 0)
        if score > 0:
            scored.append({**norm, "score": score, "matched": matched})
    scored.sort(key=lambda n: n["score"], reverse=True)
    if not scored:
        return []
    threshold = max(1.0, scored[0]["score"] * 0.34)
    return [n for n in scored if n["score"] >= threshold][:top_k]


# =============================================================================
# 4. ЖЕРГІЛІКТІ (ДЕМО) ТАЛДАУ
# =============================================================================
def required_fire_distance(a: str, b: str) -> int:
    group = {"I": 1, "II": 1, "III": 2, "IV": 3, "V": 3}
    table = {(1, 1): 6, (1, 2): 8, (1, 3): 10, (2, 2): 8, (2, 3): 10, (3, 3): 15}
    return table[tuple(sorted((group[a], group[b])))]


def analyze_locally(p: Params, norms: List[Dict]) -> Dict:
    """Ішкі ережелер бойынша тексеру. Қайтарады: verdict, findings, refs, recs."""
    active = {n["id"] for n in norms} | implied_topics(p)
    findings: List[Dict] = []

    def add(level: str, title: str, text: str, rec: str = ""):
        findings.append({"level": level, "title": title, "text": text, "rec": rec})

    # --- Өртке қарсы арақашықтық ------------------------------------------
    if "fire_distance" in active:
        d = p.neighbor_distance
        a, b = p.own_degree, p.neighbor_degree
        title = "Өртке қарсы арақашықтық"
        if not d:
            add("warning", title,
                "Көрші ғимаратқа дейінгі арақашықтық көрсетілмеген — тексеру мүмкін емес.",
                "Ғимараттар арасындағы нақты арақашықтықты (м) және отқа төзімділік дәрежелерін көрсетіңіз.")
        elif a and b:
            need = required_fire_distance(a, b)
            if d >= need:
                add("ok", title,
                    f"{a} және {b} дәрежелі ғимараттар үшін талап — кемінде {need} м; "
                    f"жобада {fmt(d)} м. Талап орындалған.")
            else:
                add("error", title,
                    f"{a} және {b} дәрежелі ғимараттар үшін талап — кемінде {need} м, ал жобада "
                    f"{fmt(d)} м (жетіспейді: {fmt(round(need - d, 2))} м).",
                    f"Арақашықтықты {need} м-ге дейін ұлғайтыңыз, не отқа төзімділік дәрежесін арттырыңыз, "
                    "не өртке қарсы қабырға (брандмауэр) мен нормада қарастырылған өтемақы шараларын қолданыңыз.")
        else:
            if d < 6:
                add("error", title,
                    f"{fmt(d)} м — отқа төзімділік дәрежесіне қарамастан ең аз талап (6 м) орындалмайды.",
                    "Арақашықтықты кем дегенде 6 м-ге дейін ұлғайтыңыз және дәрежелерді нақтылаңыз.")
            elif d >= 15:
                add("ok", title,
                    f"{fmt(d)} м — барлық отқа төзімділік дәрежелері үшін (6–15 м) жеткілікті.")
            else:
                known = a or b
                if known:
                    ok_degrees = [x for x in DEGREES[1:] if required_fire_distance(known, x) <= d]
                    detail = (f"{known} дәрежелі ғимарат үшін {fmt(d)} м арақашықтық көрші ғимарат "
                              f"дәрежесі {', '.join(ok_degrees) if ok_degrees else 'ешқайсысы'} болғанда ғана жеткілікті.")
                else:
                    detail = (f"{fmt(d)} м арақашықтық ғимараттардың отқа төзімділік дәрежесіне байланысты "
                              "жеткілікті немесе жеткіліксіз болуы мүмкін (талап 6–15 м).")
                add("warning", title, detail,
                    "Екі ғимараттың да отқа төзімділік дәрежесін (I–V) көрсетіп, қайта тексеріңіз.")
        if p.floors >= 10:
            add("warning", "Көпқабатты ғимарат",
                f"{p.floors} қабатты ғимаратқа қосымша өрт қауіпсіздігі талаптары қойылады "
                "(өрт сөндіру көліктерінің өтуі, түтінсіз баспалдақ торлары және т.б.).",
                "Қосымша талаптарды ҚР ҚН 2.02-01-2023 бойынша жеке тексеріңіз.")

    # --- Инсоляция -----------------------------------------------------------
    if "insolation" in active:
        title = "Инсоляция"
        h, o = p.insolation_hours, p.orientation
        if h:
            if h >= 2.5:
                add("ok", title, f"Инсоляция ұзақтығы {fmt(h)} сағ — талап (кемінде 2,5 сағ) орындалған.")
            else:
                add("error", title,
                    f"Инсоляция ұзақтығы {fmt(h)} сағ, ал талап — кемінде 2,5 сағ "
                    f"(жетіспейді: {fmt(round(2.5 - h, 2))} сағ).",
                    "Терезелердің бағытын өзгертіңіз, пәтерлердің жоспарлау шешімін немесе ғимараттың "
                    "орналасуын қайта қарап, инсоляциялық есепті қайталаңыз.")
        if o == "Солтүстік":
            add("error", title + " — бағыт",
                "Терезелер тек солтүстікке бағытталған: мұндай пәтерлерде нормативтік инсоляция қамтамасыз етілмейді.",
                "Тұрғын бөлмелердің кемінде біреуін оңтүстік, шығыс немесе батыс бағытқа бұрыңыз.")
        elif o in ("Солтүстік-шығыс", "Солтүстік-батыс"):
            add("warning", title + " — бағыт",
                f"{o} бағыт инсоляция бойынша шектеулі; міндетті түрде инсоляциялық есеп қажет.",
                "Инсоляциялық есеп жүргізіп, 2,5 сағ талабын растаңыз.")
        elif o and not h:
            add("warning", title + " — бағыт",
                f"Терезе бағыты — {o}: бағыт қолайлы, бірақ инсоляция ұзақтығы есептелмеген.",
                "Көршілес ғимараттардың көлеңкесін ескеріп, инсоляция ұзақтығын есептеңіз.")
        if not h and not o:
            add("warning", title,
                "Инсоляция ұзақтығы да, терезе бағыты да көрсетілмеген.",
                "Терезе бағытын және есептелген инсоляция ұзақтығын (сағ) көрсетіңіз.")

    # --- Эвакуация -------------------------------------------------------------
    if "evacuation" in active:
        title = "Эвакуациялық жолдар"
        if not p.corridor_width and not p.door_width:
            add("warning", title,
                "Дәліз бен эвакуациялық есіктің ені көрсетілмеген.",
                "Дәліздің және эвакуациялық есіктің жарықтағы енін (м) көрсетіңіз.")
        if p.corridor_width:
            if p.corridor_width >= 1.2:
                add("ok", title + " — дәліз",
                    f"Дәліз ені {fmt(p.corridor_width)} м — талап (кемінде 1,2 м) орындалған.")
            else:
                add("error", title + " — дәліз",
                    f"Дәліз ені {fmt(p.corridor_width)} м, ал талап — кемінде 1,2 м "
                    f"(жетіспейді: {fmt(round(1.2 - p.corridor_width, 2))} м).",
                    "Дәліздің енін кемінде 1,2 м-ге дейін ұлғайтыңыз (адам саны көп болса — есеппен одан да көп).")
        if p.door_width:
            if p.door_width >= 0.8:
                add("ok", title + " — есік",
                    f"Эвакуациялық есік ені {fmt(p.door_width)} м — талап (кемінде 0,8 м) орындалған.")
            else:
                add("error", title + " — есік",
                    f"Эвакуациялық есік ені {fmt(p.door_width)} м, ал талап — кемінде 0,8 м.",
                    "Есіктің жарықтағы енін кемінде 0,8 м-ге дейін ұлғайтыңыз.")

    # --- Қабат биіктігі ---------------------------------------------------------
    if "ceiling_height" in active:
        title = "Қабат биіктігі"
        if not p.floor_height:
            add("warning", title,
                "Тұрғын бөлмелердің жарықтағы биіктігі көрсетілмеген.",
                "Еден мен төбе арасындағы биіктікті (м) көрсетіңіз.")
        elif p.floor_height >= 2.7:
            add("ok", title,
                f"Биіктік {fmt(p.floor_height)} м — талап (кемінде 2,7 м) орындалған.")
        else:
            add("error", title,
                f"Биіктік {fmt(p.floor_height)} м, ал талап — кемінде 2,7 м "
                f"(жетіспейді: {fmt(round(2.7 - p.floor_height, 2))} м).",
                "Еден мен төбе арасындағы жарықтағы биіктікті кемінде 2,7 м-ге дейін көтеріңіз "
                "(қабат биіктігін немесе төбе құрылымын қайта қараңыз).")

    # --- Автотұрақ ----------------------------------------------------------------
    if "parking" in active:
        title = "Автотұрақ — терезелерге дейінгі арақашықтық"
        d, cars = p.parking_distance, p.parking_cars
        if not d:
            add("warning", title,
                "Автотұрақтан тұрғын үй терезелеріне дейінгі арақашықтық көрсетілмеген.",
                "Арақашықтықты (м) және тұрақтағы көлік санын көрсетіңіз.")
        else:
            if cars:
                need = 10 if cars <= 10 else 15 if cars <= 50 else 25
                if d >= need:
                    add("ok", title, f"{cars} көлікке талап — кемінде {need} м; жобада {fmt(d)} м. Орындалған.")
                else:
                    add("error", title,
                        f"{cars} көлікке талап — кемінде {need} м, ал жобада {fmt(d)} м "
                        f"(жетіспейді: {fmt(round(need - d, 2))} м).",
                        f"Тұрақты терезелерден кемінде {need} м-ге алыстатыңыз немесе көлік санын азайтыңыз.")
            elif d < 10:
                add("error", title,
                    f"{fmt(d)} м — ең аз талап (10 м) орындалмайды.",
                    "Тұрақты тұрғын үй терезелерінен кемінде 10 м-ге алыстатыңыз.")
            elif d < 15:
                add("warning", title,
                    f"{fmt(d)} м — 10 көлікке дейін жеткілікті, ал 11–50 көлікке 15 м қажет.",
                    "Тұрақтағы көлік санын көрсетіп, қайта тексеріңіз.")
            else:
                add("ok", title, f"{fmt(d)} м — 50 көлікке дейінгі тұрақ үшін жеткілікті.")

    # --- Өрт сөндіру өтпесі ---------------------------------------------------------
    if "fire_access" in active:
        title = "Өрт сөндіру көліктерінің өтпесі"
        if not p.driveway_width:
            add("warning", title,
                "Өтпе жолдың ені көрсетілмеген.",
                "Өрт сөндіру көліктеріне арналған өтпенің енін (м) көрсетіңіз.")
        else:
            high = p.floors > 4
            need = 4.2 if high else 3.5
            suffix = " (шамамен 13 м-ден биік ғимарат)" if high else ""
            if p.driveway_width >= need:
                add("ok", title,
                    f"Өтпе ені {fmt(p.driveway_width)} м — талап (кемінде {fmt(need)} м){suffix} орындалған.")
            else:
                add("error", title,
                    f"Өтпе ені {fmt(p.driveway_width)} м, ал талап — кемінде {fmt(need)} м{suffix}.",
                    f"Өтпе енін кемінде {fmt(need)} м-ге дейін ұлғайтыңыз.")

    # --- Қорытынды --------------------------------------------------------------------
    levels = [f["level"] for f in findings]
    if "error" in levels:
        verdict = "fail"
    elif not findings or "warning" in levels:
        verdict = "clarify"
    else:
        verdict = "ok"

    if not findings:
        add("warning", "Деректер жеткіліксіз",
            "Сұраудан тексеруге болатын тақырып не параметр анықталмады.",
            "Өрт қауіпсіздігі, инсоляция, эвакуация, қабат биіктігі немесе автотұрақ бойынша "
            "нақты сандық мәндерді (м, сағат) көрсетіңіз.")

    refs = []
    for tid in [n["id"] for n in NORMS if n["id"] in active]:
        n = NORMS_BY_ID[tid]
        refs.append(f"**{n['doc']}** — {n['clause']}: {n['topic']}")

    recs = [f["rec"] for f in findings if f["rec"]]
    recs.append("Түпкілікті шешімді жобалау құжаттамасының ресми сараптамасында растаңыз.")
    return {"verdict": verdict, "findings": findings, "refs": refs, "recs": recs}


VERDICT_LABELS = {
    "ok": "Сәйкес келеді",
    "fail": "Сәйкес келмейді",
    "clarify": "Нақтылау қажет",
}


def local_report_text(res: Dict, query: str) -> str:
    lines = [
        f"NormAI — тексеру есебі (демо-режим)",
        "",
        f"Сұрау: {query.strip() or '—'}",
        "",
        f"📊 Жалпы қорытынды: {VERDICT_LABELS[res['verdict']]}",
        "",
        "📌 Нормативтік сілтемелер:",
    ]
    lines += [f"- {r.replace('**', '')}" for r in res["refs"]] or ["- табылмады"]
    lines += ["", "⚠️ Анықталған қателіктер мен тәуекелдер:"]
    for f in res["findings"]:
        mark = {"error": "❌", "warning": "⚠️", "ok": "✅"}[f["level"]]
        lines.append(f"- {mark} {f['title']}: {f['text']}")
    lines += ["", "💡 Түзету бойынша ұсыныстар:"]
    lines += [f"- {r}" for r in res["recs"]]
    return "\n".join(lines)


# =============================================================================
# 5. GEMINI (RAG генерациясы)
# =============================================================================
SYSTEM_PROMPT = """Сен — Қазақстан Республикасының сәулет-құрылыс нормалары бойынша тәжірибелі сарапшы-сәулетшісің (NormAI жүйесі).
Міндетің: пайдаланушы сипаттаған жобалық шешімді ҚР нормативтік талаптарымен (ҚНжЕ / ҚР ЕЖ / ҚР ҚН) салыстырып тексеру.

ЕРЕЖЕЛЕР:
1. Тек ҚАЗАҚ тілінде жауап бер. Стиль — ресми, нақты, кәсіби.
2. Нормативтік талаптарды ТЕК берілген «НОРМАТИВТІК КОНТЕКСТ» ішінен ал. Контексте жоқ тармақ нөмірін, кесте нөмірін немесе санды ойдан шығарма.
   Егер контекст жеткіліксіз болса, соны ашық айтып, «Нақтылау қажет» деп бағала.
3. Пайдаланушы деректері жетіспесе, нақты қандай деректер керек екенін көрсет.
4. Есептеулерді (айырма, жетіспейтін мөлшер) көрсет.
5. Жауапты дәл мына төрт блокпен, Markdown форматында құрылымда:

## 📊 Жалпы қорытынды
(Бір ғана бағаны таңда: **Сәйкес келеді** / **Сәйкес келмейді** / **Нақтылау қажет** — және 1–2 сөйлем түсініктеме)

## 📌 Нормативтік сілтемелер
(Қолданылған құжаттар мен талаптар тізімі: құжат атауы, талап мазмұны)

## ⚠️ Анықталған қателіктер мен тәуекелдер
(Нормадан ауытқулар, олардың мөлшері; тәуекелдер)

## 💡 Түзету бойынша ұсыныстар
(Нақты, орындалатын шаралар)

6. Соңында бір сөйлеммен ескерт: бұл ЖИ-талдау, ресми сараптама емес.
"""


def build_prompt(query: str, p: Params, norms: List[Dict]) -> str:
    context = "\n\n".join(
        f"[{i}] {n['doc']} — {n['clause']}\nТақырып: {n['topic']}\nТалап: {n['text']}"
        for i, n in enumerate(norms, 1)
    ) or "(Ішкі базадан сәйкес үзінді табылмады — бұл жағдайда сақ бол және нақтылау қажет екенін айт.)"
    param_lines = "\n".join(f"- {line}" for line in params_to_lines(p)) or "- (қосымша параметрлер берілмеген)"
    return (
        f"НОРМАТИВТІК КОНТЕКСТ:\n{context}\n\n"
        f"ЖОБА ПАРАМЕТРЛЕРІ:\n{param_lines}\n\n"
        f"ПАЙДАЛАНУШЫ СҰРАУЫ:\n{query.strip() or '(мәтіндік сипаттама берілмеген, тек параметрлер бойынша тексер)'}"
    )


def call_gemini(api_key: str, query: str, p: Params, norms: List[Dict]) -> str:
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=build_prompt(query, p, norms),
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.2,
        ),
    )
    text = (response.text or "").strip()
    if not text:
        raise RuntimeError("Модель бос жауап қайтарды.")
    return text


def detect_verdict(markdown_text: str) -> str:
    """Модель жауабынан жалпы қорытындыны анықтайды."""
    m = re.search(r"жалпы қорытынды(.{0,400})", markdown_text, re.IGNORECASE | re.DOTALL)
    chunk = (m.group(1) if m else markdown_text[:500]).lower()
    if "сәйкес келмейді" in chunk:
        return "fail"
    if "нақтылау қажет" in chunk:
        return "clarify"
    if "сәйкес келеді" in chunk:
        return "ok"
    return "clarify"


# =============================================================================
# 6. UI
# =============================================================================
CUSTOM_CSS = """
<style>
.block-container {padding-top: 2rem; max-width: 1150px;}
.nx-hero {
    border-left: 6px solid #8d6e4a;
    background: linear-gradient(90deg, rgba(141,110,74,0.14), rgba(141,110,74,0.02));
    padding: 1.1rem 1.5rem; border-radius: 6px; margin-bottom: 1.2rem;
}
.nx-hero h1 {margin: 0; font-size: 2.2rem; letter-spacing: 0.04em;}
.nx-hero p {margin: 0.3rem 0 0 0; opacity: 0.8; font-size: 1.02rem;}
div.stButton > button {width: 100%; border-radius: 4px;}
.nx-doc {font-size: 0.88rem; margin-bottom: 0.55rem; line-height: 1.3;}
.nx-doc span {opacity: 0.7;}
.nx-foot {font-size: 0.78rem; opacity: 0.65;}
</style>
"""


def get_secret_key() -> str:
    try:
        return st.secrets.get("GEMINI_API_KEY", "")
    except Exception:
        return ""


def set_example(text: str) -> None:
    st.session_state["query_text"] = text


def render_sidebar() -> tuple:
    with st.sidebar:
        st.markdown("## 🏛️ NormAI")
        st.caption("Жоба туралы")
        st.markdown(
            "**NormAI** — «ArchiCore» командасының (**АЖиОЗ 25-4** тобы) университеттік жобасы. "
            "Ассистент жобалық шешімді ҚР құрылыс нормаларымен салыстырып, нормативтік "
            "сілтемелері бар талдау береді (RAG: іздеу + генерация)."
        )
        st.divider()

        mode = st.radio("Жұмыс режимі", [MODE_API, MODE_DEMO], index=0)
        api_key = ""
        if mode == MODE_API:
            api_key = st.text_input(
                "Google Gemini API кілті",
                type="password",
                value=get_secret_key(),
                placeholder="AIza...",
                help="Кілтті Google AI Studio сайтынан тегін алуға болады. Кілт сақталмайды.",
            )
            if not api_key:
                st.info("Кілт енгізілмесе, талдау демо-режимде орындалады.")
        else:
            st.caption("Демо-режимде талдау ішкі ережелер бойынша, интернетсіз жүреді.")

        st.divider()
        st.markdown("#### 📚 Қосылған нормативтік базалар")
        for code, desc in SIDEBAR_DOCS:
            st.markdown(f"<div class='nx-doc'><b>{code}</b><br><span>{desc}</span></div>", unsafe_allow_html=True)
        st.divider()
        st.markdown(
            "<div class='nx-foot'>Нәтиже — анықтамалық сипатта және ресми сараптаманы алмастырмайды. "
            "Ішкі база оқу мақсатында жинақталған: нақты жобада құжаттардың қолданыстағы "
            "басылымын тексеріңіз.</div>",
            unsafe_allow_html=True,
        )
    return mode, api_key


def render_input() -> tuple:
    st.markdown("### 🧪 Үлгі сұраулар")
    cols = st.columns(3)
    for col, key in zip(cols, ["fire", "insolation", "evacuation"]):
        ex = EXAMPLES[key]
        col.button(ex["label"], key=f"ex_{key}", on_click=set_example, args=(ex["text"],))

    st.markdown("### ✍️ Жобалық шешімді сипаттаңыз")
    st.text_area(
        "Планировкалық шешімнің немесе нысан параметрлерінің сипаттамасы",
        key="query_text",
        height=150,
        placeholder="Мысалы: 9 қабатты тұрғын үй мен көрші ғимарат арасындағы арақашықтық 6 м ...",
    )

    c1, c2, c3 = st.columns(3)
    floors = c1.number_input("Ғимарат қабаттылығы", min_value=0, max_value=200, value=0, step=1,
                             help="0 — көрсетілмеген (мәтіннен автоматты түрде ізделеді)")
    distance = c2.number_input("Көрші ғимаратқа дейінгі арақашықтық, м", min_value=0.0, max_value=500.0,
                               value=0.0, step=0.5, help="0 — көрсетілмеген")
    orientation = c3.selectbox("Терезе бағыты", DIRECTIONS)

    with st.expander("➕ Қосымша параметрлер (міндетті емес)"):
        e1, e2, e3 = st.columns(3)
        own_degree = e1.selectbox("Ғимараттың отқа төзімділік дәрежесі", DEGREES)
        neighbor_degree = e2.selectbox("Көрші ғимараттың отқа төзімділік дәрежесі", DEGREES)
        hours = e3.number_input("Инсоляция ұзақтығы, сағ", min_value=0.0, max_value=24.0, value=0.0, step=0.1)
        e4, e5, e6 = st.columns(3)
        corridor = e4.number_input("Эвакуациялық дәліз ені, м", min_value=0.0, max_value=20.0, value=0.0, step=0.1)
        door = e5.number_input("Эвакуациялық есік ені, м", min_value=0.0, max_value=10.0, value=0.0, step=0.05)
        height = e6.number_input("Қабат биіктігі (жарықтағы), м", min_value=0.0, max_value=10.0, value=0.0, step=0.05)
        e7, e8, e9 = st.columns(3)
        parking = e7.number_input("Автотұрақтан терезеге дейін, м", min_value=0.0, max_value=200.0, value=0.0, step=0.5)
        cars = e8.number_input("Тұрақтағы көлік саны", min_value=0, max_value=1000, value=0, step=1)
        driveway = e9.number_input("Өрт сөндіру өтпесінің ені, м", min_value=0.0, max_value=20.0, value=0.0, step=0.1)

    form = Params(
        floors=int(floors),
        neighbor_distance=float(distance),
        orientation="" if orientation == DIRECTIONS[0] else orientation,
        own_degree="" if own_degree == DEGREES[0] else own_degree,
        neighbor_degree="" if neighbor_degree == DEGREES[0] else neighbor_degree,
        corridor_width=float(corridor),
        door_width=float(door),
        floor_height=float(height),
        parking_distance=float(parking),
        parking_cars=int(cars),
        insolation_hours=float(hours),
        driveway_width=float(driveway),
    )
    return st.session_state.get("query_text", ""), form


def run_check(query: str, form: Params, mode: str, api_key: str) -> Optional[Dict]:
    extracted = extract_from_text(query)
    params = merge_params(form, extracted)
    norms = retrieve_norms(query + " " + " ".join(params_to_lines(params)), hints=implied_topics(params))

    result = {"params": params, "norms": norms, "query": query, "api_text": None,
              "local": None, "notice": None}

    use_api = mode == MODE_API and bool(api_key)
    if mode == MODE_API and not api_key:
        result["notice"] = ("info", "API кілті енгізілмеген — талдау демо-режимде орындалды.")
    if use_api and not GENAI_AVAILABLE:
        use_api = False
        result["notice"] = ("warning", "google-genai кітапханасы орнатылмаған (pip install google-genai). "
                                       "Талдау демо-режимде орындалды.")

    if use_api:
        try:
            with st.spinner("Gemini нормативтік базамен талдап жатыр..."):
                result["api_text"] = call_gemini(api_key, query, params, norms)
        except Exception as exc:  # желі, кілт, квота қателері
            result["notice"] = ("error", f"Gemini сұрауы орындалмады: {exc}. Демо-режимге ауыстық.")

    if result["api_text"] is None:
        result["local"] = analyze_locally(params, norms)
    return result


def render_norm_fragments(result: Dict) -> None:
    with st.expander(f"🔎 RAG: табылған нормативтік фрагменттер ({len(result['norms'])})"):
        if not result["norms"]:
            st.write("Ішкі базадан сәйкес үзінді табылмады. Сұрауға кілт сөздер (өрт, инсоляция, эвакуация, "
                     "биіктік, автотұрақ) қосып көріңіз.")
        for n in result["norms"]:
            st.markdown(f"**{n['doc']}** — {n['clause']}")
            st.caption(f"Тақырып: {n['topic']} · сәйкестік: {n['score']} · кілт сөздер: "
                       f"{', '.join(n['matched']) if n['matched'] else 'параметрлер бойынша'}")
            st.write(n["text"])
            st.divider()


def render_result(result: Dict) -> None:
    st.markdown("---")
    st.markdown("## 📋 Тексеру нәтижесі")

    if result["notice"]:
        kind, msg = result["notice"]
        getattr(st, kind)(msg)

    detected = [line for line in params_to_lines(result["params"])]
    if detected:
        with st.expander("🧾 Талдауға қабылданған параметрлер"):
            for line in detected:
                st.markdown(f"- {line}")

    if result["api_text"]:
        verdict = detect_verdict(result["api_text"])
        banner = f"📊 Жалпы қорытынды (Gemini): {VERDICT_LABELS[verdict]}"
        {"ok": st.success, "fail": st.error, "clarify": st.warning}[verdict](banner)
        with st.container(border=True):
            st.markdown(result["api_text"])
        report = result["api_text"]
    else:
        res = result["local"]
        banner = f"📊 Жалпы қорытынды: {VERDICT_LABELS[res['verdict']]}"
        {"ok": st.success, "fail": st.error, "clarify": st.warning}[res["verdict"]](banner)

        st.markdown("#### 📌 Нормативтік сілтемелер")
        if res["refs"]:
            st.info("\n\n".join(f"• {r}" for r in res["refs"]))
        else:
            st.info("Нақты норма табылмады.")

        st.markdown("#### ⚠️ Анықталған қателіктер мен тәуекелдер")
        shown = False
        for f in res["findings"]:
            if f["level"] == "error":
                st.error(f"**{f['title']}.** {f['text']}")
                shown = True
        for f in res["findings"]:
            if f["level"] == "warning":
                st.warning(f"**{f['title']}.** {f['text']}")
                shown = True
        for f in res["findings"]:
            if f["level"] == "ok":
                st.success(f"✅ **{f['title']}.** {f['text']}")
                shown = True
        if not shown:
            st.info("Қателіктер анықталмады.")

        st.markdown("#### 💡 Түзету бойынша ұсыныстар")
        st.info("\n\n".join(f"• {r}" for r in res["recs"]))
        report = local_report_text(res, result["query"])

    render_norm_fragments(result)
    st.download_button("⬇️ Есепті жүктеу (.txt)", data=report, file_name="normai_report.txt",
                       mime="text/plain")


def main() -> None:
    st.set_page_config(page_title="NormAI — ҚР нормаларын тексеру", page_icon="🏛️", layout="wide",
                       initial_sidebar_state="expanded")
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
    st.session_state.setdefault("query_text", "")

    mode, api_key = render_sidebar()

    st.markdown(
        f"<div class='nx-hero'><h1>🏛️ {APP_TITLE}</h1><p>{APP_SUBTITLE}</p></div>",
        unsafe_allow_html=True,
    )

    query, form = render_input()

    if st.button("🔍 Нормаларға сәйкестікті тексеру", type="primary"):
        if not query.strip() and not params_to_lines(form):
            st.warning("Жобалық шешімді сипаттаңыз немесе кемінде бір параметрді көрсетіңіз.")
        else:
            st.session_state["result"] = run_check(query, form, mode, api_key)

    if st.session_state.get("result"):
        render_result(st.session_state["result"])


if __name__ == "__main__":
    main()
