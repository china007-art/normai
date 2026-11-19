# -*- coding: utf-8 -*-
"""
NormAI v2 — ЖИ-ассистент для проверки соответствия строительным нормам РК
(ҚНжЕ / ҚР ЕЖ / ҚР ҚН · СНиП / СП / СН РК).

Команда ArchiCore · группа АЖиОЗ 25-4 · КазГАСА

Структура одного файла:
    1. Константы и справочники
    2. I18N          — переводы интерфейса и шаблонов отчётов (kk / ru / en)
    3. Нормативная база (RAG knowledge base) и retrieve_norms()
    4. Извлечение параметров из текста и правиловый анализ (демо-режим)
    5. Gemini-генерация (RAG)
    6. Отчёты (TXT / PDF)
    7. UI-компоненты и стили
    8. Страницы: Главная · Инспектор · База нормативов · История и отчёты
    9. Точка входа (st.navigation)

Справочные выдержки в базе носят учебный характер: перед использованием в реальном
проекте сверяйте значения с действующей официальной редакцией документов.
"""

from __future__ import annotations

import html
import json
import os
import re
import time
import uuid
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import streamlit as st

try:  # Google Gen AI SDK:  pip install google-genai
    from google import genai
    from google.genai import types

    GENAI_AVAILABLE = True
except Exception:  # pragma: no cover
    GENAI_AVAILABLE = False


# =============================================================================
# 1. КОНСТАНТЫ
# =============================================================================
APP_NAME = "NormAI"
APP_VERSION = "2.0"
MODEL_NAME = "gemini-2.5-flash"
MAX_SERVER_KEY_CALLS = 15  # лимит запросов за сессию при использовании серверного ключа
LANGS = ["kk", "ru", "en"]
LANG_IDX = {"kk": 0, "ru": 1, "en": 2}
LANG_LABELS = {"kk": "🇰🇿 Қазақша", "ru": "🇷🇺 Русский", "en": "🇬🇧 English"}
LANG_NAMES = {"kk": "Kazakh", "ru": "Russian", "en": "English"}

DEGREES = ["", "I", "II", "III", "IV", "V"]
DIRECTIONS = ["", "N", "NE", "E", "SE", "S", "SW", "W", "NW"]

PAGES: Dict[str, object] = {}  # заполняется в main(), используется для st.switch_page


def L() -> str:
    """Текущий язык интерфейса."""
    return st.session_state.get("lang", "kk")


def now_str() -> str:
    return datetime.now(timezone(timedelta(hours=5))).strftime("%Y-%m-%d %H:%M")


# =============================================================================
# 2. I18N — (kk, ru, en)
# =============================================================================
S: Dict[str, Tuple[str, str, str]] = {
    # --- навигация / общее ---------------------------------------------------
    "nav_dashboard": ("Басты бет", "Главная", "Dashboard"),
    "nav_inspector": ("Нормалар инспекторы", "Инспектор норм", "Norm Inspector"),
    "nav_norms": ("Нормативтер базасы", "База нормативов", "Standards Library"),
    "nav_history": ("Тарих және есептер", "История и отчёты", "History & Reports"),
    "kick_dashboard": ("01 / Шолу", "01 / Обзор", "01 / Overview"),
    "kick_inspector": ("02 / Тексеру", "02 / Проверка", "02 / Inspection"),
    "kick_norms": ("03 / Анықтамалық", "03 / Справочник", "03 / Reference"),
    "kick_history": ("04 / Архив", "04 / Архив", "04 / Archive"),
    # --- сайдбар ---------------------------------------------------------------
    "lang_label": ("Тіл", "Язык", "Language"),
    "mode_label": ("Жұмыс режимі", "Режим работы", "Operating mode"),
    "mode_api": ("ЖИ-талдау (API арқылы)", "ИИ-анализ (через API)", "AI analysis (API)"),
    "mode_demo": ("Демо-режим (кілтсіз)", "Демо-режим (без ключа)", "Demo mode (no key)"),
    "api_key": ("Google Gemini API кілті", "Ключ Google Gemini API", "Google Gemini API key"),
    "api_key_help": (
        "Кілт тек осы сессияда қолданылады және сақталмайды. Google AI Studio-дан алуға болады.",
        "Ключ используется только в рамках сессии и не сохраняется. Получить его можно в Google AI Studio.",
        "The key is used for this session only and is never stored. Get one in Google AI Studio.",
    ),
    "server_key": (
        "Серверлік кілт қосылған. Өз кілтіңізді енгізсеңіз, ол басым болады.",
        "Серверный ключ подключён. Ваш собственный ключ имеет приоритет.",
        "A server key is configured. Your own key takes priority.",
    ),
    "no_key_note": (
        "Кілт енгізілмесе, талдау демо-режимде орындалады.",
        "Без ключа анализ выполняется в демо-режиме.",
        "Without a key the analysis runs in demo mode.",
    ),
    "demo_note": (
        "Демо-режим ішкі ережелер бойынша, интернетсіз жұмыс істейді.",
        "Демо-режим работает локально, по встроенным правилам, без обращения к сети.",
        "Demo mode runs a local rule-based analysis with no network calls.",
    ),
    "sb_foot": (
        "Нәтиже анықтамалық сипатта және ресми сараптаманы алмастырмайды.",
        "Результат носит справочный характер и не заменяет официальную экспертизу.",
        "Results are informational and do not replace formal expert review.",
    ),
    "team": (
        "ArchiCore командасы · АЖиОЗ 25-4 тобы · ҚазБСҚА",
        "Команда ArchiCore · группа АЖиОЗ 25-4 · КазГАСА",
        "ArchiCore team · group AZhiOZ 25-4 · KazGASA",
    ),
    # --- главная ------------------------------------------------------------------
    "dash_title": ("Басқару панелі", "Панель управления", "Dashboard"),
    "dash_sub": (
        "ҚР құрылыс нормаларына сәйкестікті тексеруге арналған жұмыс орны",
        "Рабочее место для проверки проектных решений на соответствие строительным нормам РК",
        "Workspace for checking design decisions against Kazakhstan construction standards",
    ),
    "about_title": ("Жоба туралы", "О проекте", "About the project"),
    "about_text": (
        "NormAI — жобалық шешімді ҚР құрылыс нормаларымен (ҚНжЕ, ҚР ЕЖ, ҚР ҚН) салыстыратын ассистент. "
        "Жүйе RAG тәсілімен жұмыс істейді: алдымен нормативтік базадан тиісті талаптар іріктеледі, "
        "содан кейін олар Gemini моделіне контекст ретінде беріледі. API кілті болмаса, ішкі ережелерге "
        "негізделген демо-режим қолданылады.",
        "NormAI — ассистент, который сопоставляет проектное решение со строительными нормами РК "
        "(СНиП, СП и СН РК). Система работает по схеме RAG: сначала из нормативной базы отбираются "
        "релевантные требования, затем они передаются модели Gemini как контекст. Без API-ключа "
        "используется демо-режим на встроенных правилах.",
        "NormAI compares a design decision with Kazakhstan construction standards (SNiP, SP and SN RK). "
        "It follows a RAG scheme: relevant provisions are retrieved from the library first and then passed "
        "to Gemini as context. Without an API key a built-in rule engine runs in demo mode.",
    ),
    "kpi_checks": ("Тексерулер", "Проверок выполнено", "Checks performed"),
    "kpi_fail": ("Сәйкес келмейді", "Не соответствует", "Non-compliant"),
    "kpi_clarify": ("Нақтылау қажет", "Требует уточнения", "Needs clarification"),
    "kpi_norms": ("Базадағы талаптар", "Требований в базе", "Provisions in library"),
    "kpi_session": ("ағымдағы сессия", "текущая сессия", "current session"),
    "kpi_docs": ("{n} құжат", "{n} документа", "{n} documents"),
    "quick_title": ("Жылдам іске қосу", "Быстрый запуск", "Quick start"),
    "quick_sub": (
        "Дайын сценарийді таңдаңыз — Инспектор автоматты түрде ашылады.",
        "Выберите готовый сценарий — Инспектор откроется автоматически.",
        "Pick a ready scenario — the Inspector opens automatically.",
    ),
    "how_title": ("Жұмыс принципі", "Как это работает", "How it works"),
    "how1_t": ("Сипаттау", "Описание", "Describe"),
    "how1_d": (
        "Шешімді еркін мәтінмен сипаттаңыз немесе параметрлерді енгізіңіз.",
        "Опишите решение свободным текстом или введите параметры.",
        "Describe the design in free text or enter parameters.",
    ),
    "how2_t": ("Іздеу (RAG)", "Поиск (RAG)", "Retrieve (RAG)"),
    "how2_d": (
        "Жүйе нормативтік базадан тиісті талаптарды іріктейді.",
        "Система отбирает релевантные требования из нормативной базы.",
        "The system retrieves the relevant provisions from the library.",
    ),
    "how3_t": ("Талдау", "Анализ", "Analyse"),
    "how3_d": (
        "Gemini немесе ішкі ережелер қорытынды, тәуекелдер мен ұсыныстар береді.",
        "Gemini или встроенные правила формируют заключение, риски и рекомендации.",
        "Gemini or the built-in rules produce a verdict, risks and recommendations.",
    ),
    "coverage": ("Қамтылған бағыттар", "Охватываемые направления", "Coverage"),
    "verdict_dist": ("Қорытындылар бөлінісі", "Распределение заключений", "Verdict distribution"),
    "topic_freq": ("Жиі тексерілетін тақырыптар", "Частые темы проверок", "Most checked topics"),
    "recent": ("Соңғы тексерулер", "Последние проверки", "Recent checks"),
    "no_data": (
        "Әзірге деректер жоқ. Алғашқы тексеруді іске қосыңыз.",
        "Данных пока нет. Запустите первую проверку.",
        "No data yet. Run your first check.",
    ),
    # --- примеры ---------------------------------------------------------------------
    "ex_fire": ("Өртке қарсы арақашықтық", "Противопожарные разрывы", "Fire separation distance"),
    "ex_ins": ("Тұрғын үй инсоляциясы", "Инсоляция жилых помещений", "Residential insolation"),
    "ex_evac": ("Эвакуация жолдарының ені", "Ширина эвакуационных путей", "Evacuation route width"),
    "ex_fire_text": (
        "9 қабатты тұрғын үй (II дәрежелі отқа төзімділік) мен көрші 3 қабатты қоғамдық ғимарат "
        "(III дәрежелі) арасындағы арақашықтық 6 м. Өртке қарсы арақашықтық талаптарына сәйкес келе ме?",
        "Расстояние между 9-этажным жилым зданием (II степень огнестойкости) и соседним 3-этажным "
        "общественным зданием (III степень огнестойкости) составляет 6 м. Соответствует ли оно "
        "противопожарным требованиям?",
        "The distance between a 9-storey residential building (fire resistance degree II) and a "
        "neighbouring 3-storey public building (fire resistance degree III) is 6 m. Does it comply "
        "with the fire separation requirements?",
    ),
    "ex_ins_text": (
        "Алматыдағы тұрғын үйдің бір бөлмелі пәтерінің терезесі солтүстікке қараған. "
        "Инсоляция ұзақтығы 1,5 сағат. Нормаға сәйкес келе ме?",
        "Окно однокомнатной квартиры в жилом доме в Алматы ориентировано на север. "
        "Продолжительность инсоляции — 1,5 ч. Соответствует ли это норме?",
        "The window of a one-room apartment in Almaty faces north. The insolation duration is "
        "1.5 hours. Does it comply with the standard?",
    ),
    "ex_evac_text": (
        "Кеңсе ғимаратының эвакуациялық дәлізінің ені 1,0 м, эвакуациялық есіктің ені 0,8 м. "
        "Ғимарат 5 қабатты. Талаптарға сәйкес келе ме?",
        "Ширина эвакуационного коридора офисного здания — 1,0 м, ширина эвакуационной двери — 0,8 м. "
        "Здание 5-этажное. Соответствует ли оно требованиям?",
        "The evacuation corridor of an office building is 1.0 m wide and the evacuation door is 0.8 m "
        "wide. The building has 5 floors. Does it meet the requirements?",
    ),
    # --- инспектор ---------------------------------------------------------------------
    "insp_title": ("Нормалар инспекторы", "Инспектор норм", "Norm Inspector"),
    "insp_sub": (
        "Жобалық шешімді сипаттаңыз — жүйе тиісті нормаларды тауып, сәйкестікті бағалайды.",
        "Опишите проектное решение — система найдёт релевантные нормы и оценит соответствие.",
        "Describe the design — the system retrieves the provisions and assesses compliance.",
    ),
    "samples": ("Үлгі сұраулар", "Образцы запросов", "Sample queries"),
    "desc_label": (
        "Жобалық шешімнің немесе нысан параметрлерінің сипаттамасы",
        "Описание проектного решения или параметров объекта",
        "Description of the design or object parameters",
    ),
    "desc_ph": (
        "Мысалы: тұрғын үй мен көрші ғимарат арасындағы арақашықтық 8 м, отқа төзімділік дәрежесі II ...",
        "Например: расстояние между жилым домом и соседним зданием 8 м, степень огнестойкости II ...",
        "For example: the distance between the residential building and the neighbouring one is 8 m, "
        "fire resistance degree II ...",
    ),
    "f_floors": ("Ғимарат қабаттылығы", "Этажность здания", "Number of storeys"),
    "f_distance": (
        "Көрші ғимаратқа дейінгі арақашықтық, м",
        "Расстояние до соседнего здания, м",
        "Distance to neighbouring building, m",
    ),
    "f_orient": ("Терезе бағыты", "Ориентация окон", "Window orientation"),
    "extra": ("Қосымша параметрлер", "Дополнительные параметры", "Additional parameters"),
    "f_own": (
        "Ғимараттың отқа төзімділік дәрежесі",
        "Степень огнестойкости здания",
        "Building fire resistance degree",
    ),
    "f_nb": (
        "Көрші ғимараттың отқа төзімділік дәрежесі",
        "Степень огнестойкости соседнего здания",
        "Neighbouring building fire resistance degree",
    ),
    "f_hours": ("Инсоляция ұзақтығы, сағ", "Продолжительность инсоляции, ч", "Insolation duration, h"),
    "f_corr": (
        "Эвакуациялық дәліз ені, м",
        "Ширина эвакуационного коридора, м",
        "Evacuation corridor width, m",
    ),
    "f_door": (
        "Эвакуациялық есік ені, м",
        "Ширина эвакуационной двери, м",
        "Evacuation door width, m",
    ),
    "f_height": (
        "Қабат биіктігі (жарықтағы), м",
        "Высота этажа (в свету), м",
        "Storey clear height, m",
    ),
    "f_park": (
        "Автотұрақтан терезеге дейін, м",
        "От парковки до окон, м",
        "Parking to windows, m",
    ),
    "f_cars": ("Тұрақтағы көлік саны", "Количество машин на парковке", "Number of parked cars"),
    "f_drive": (
        "Өрт сөндіру өтпесінің ені, м",
        "Ширина проезда для пожарной техники, м",
        "Fire access width, m",
    ),
    "zero_help": (
        "0 — көрсетілмеген; мән мәтіннен автоматты түрде ізделеді",
        "0 — не задано; значение автоматически ищется в тексте",
        "0 means not set; the value is auto-detected from the text",
    ),
    "not_set": ("Көрсетілмеген", "Не указано", "Not specified"),
    "run": ("Сәйкестікті тексеру", "Проверить соответствие", "Run compliance check"),
    "empty_input": (
        "Шешімді сипаттаңыз немесе кемінде бір параметрді көрсетіңіз.",
        "Опишите решение или укажите хотя бы один параметр.",
        "Describe the design or provide at least one parameter.",
    ),
    "spin": (
        "Gemini нормативтік контекстпен талдап жатыр...",
        "Gemini анализирует запрос с нормативным контекстом...",
        "Gemini is analysing the request with the retrieved context...",
    ),
    "n_nokey": (
        "API кілті енгізілмеген — талдау демо-режимде орындалды.",
        "API-ключ не указан — анализ выполнен в демо-режиме.",
        "No API key provided — the analysis ran in demo mode.",
    ),
    "n_nolib": (
        "google-genai кітапханасы орнатылмаған — талдау демо-режимде орындалды.",
        "Библиотека google-genai не установлена — анализ выполнен в демо-режиме.",
        "The google-genai library is not installed — the analysis ran in demo mode.",
    ),
    "n_fail": (
        "Gemini сұрауы орындалмады ({err}). Талдау демо-режимде орындалды.",
        "Запрос к Gemini не выполнен ({err}). Анализ выполнен в демо-режиме.",
        "The Gemini request failed ({err}). The analysis ran in demo mode.",
    ),
    "n_limit": (
        "Серверлік кілт бойынша сессия лимиті таусылды. Өз кілтіңізді енгізіңіз; талдау демо-режимде орындалды.",
        "Лимит запросов по серверному ключу исчерпан. Введите свой ключ; анализ выполнен в демо-режиме.",
        "The session limit for the server key is exhausted. Enter your own key; the analysis ran in demo mode.",
    ),
    "result_title": ("Тексеру нәтижесі", "Результат проверки", "Inspection result"),
    "used_params": (
        "Талдауға қабылданған параметрлер",
        "Параметры, принятые к анализу",
        "Parameters used in the analysis",
    ),
    "verdict_lbl": ("Жалпы қорытынды", "Общее заключение", "Overall verdict"),
    "v_ok": ("Сәйкес келеді", "Соответствует", "Compliant"),
    "v_fail": ("Сәйкес келмейді", "Не соответствует", "Non-compliant"),
    "v_clarify": ("Нақтылау қажет", "Требуется уточнение", "Clarification required"),
    "src_ai": ("Gemini талдауы", "Анализ Gemini", "Gemini analysis"),
    "src_rule": ("Ережелер бойынша талдау", "Анализ по правилам", "Rule-based analysis"),
    "sec_refs": ("Нормативтік сілтемелер", "Нормативные ссылки", "Normative references"),
    "sec_find": (
        "Анықталған ауытқулар мен тәуекелдер",
        "Выявленные отклонения и риски",
        "Deviations and risks",
    ),
    "sec_recs": ("Түзету бойынша ұсыныстар", "Рекомендации по устранению", "Recommendations"),
    "sec_frag": (
        "RAG: табылған нормативтік фрагменттер",
        "RAG: найденные нормативные фрагменты",
        "RAG: retrieved provisions",
    ),
    "sec_query": ("Сұрау", "Запрос", "Query"),
    "ai_block": ("Gemini қорытындысы", "Заключение Gemini", "Gemini assessment"),
    "rule_block": (
        "Ережелер бойынша қосымша тексеру",
        "Перекрёстная проверка по правилам",
        "Rule-based cross-check",
    ),
    "matched": ("кілт сөздер", "ключевые слова", "keywords"),
    "score": ("сәйкестік", "релевантность", "relevance"),
    "by_params": ("параметрлер бойынша", "по параметрам", "from parameters"),
    "no_frag": (
        "Базадан сәйкес үзінді табылмады. Сұрауға кілт сөздер қосып көріңіз (өрт, инсоляция, эвакуация, биіктік, автотұрақ).",
        "Подходящих фрагментов не найдено. Добавьте ключевые слова (пожар, инсоляция, эвакуация, высота, парковка).",
        "No matching provisions found. Add keywords (fire, insolation, evacuation, height, parking).",
    ),
    "dl_txt": ("Есепті жүктеу (.txt)", "Скачать отчёт (.txt)", "Download report (.txt)"),
    "dl_pdf": ("Есепті жүктеу (.pdf)", "Скачать отчёт (.pdf)", "Download report (.pdf)"),
    "pdf_na": (
        "PDF жасау мүмкін емес: Unicode қаріпі табылмады (matplotlib немесе fonts-dejavu-core орнатыңыз). TXT қолжетімді.",
        "Формирование PDF недоступно: не найден Unicode-шрифт (установите matplotlib или fonts-dejavu-core). TXT доступен.",
        "PDF export is unavailable: no Unicode font found (install matplotlib or fonts-dejavu-core). TXT is available.",
    ),
    "saved": (
        "Нәтиже тарихқа сақталды.",
        "Результат сохранён в истории.",
        "Result saved to history.",
    ),
    "lvl_error": ("Ауытқу", "Отклонение", "Deviation"),
    "lvl_warning": ("Нақтылау", "Уточнение", "Clarify"),
    "lvl_ok": ("Сәйкес", "Соответствует", "Compliant"),
    "ai_disc": (
        "Бұл ЖИ-талдау және ресми сараптаманы алмастырмайды.",
        "Это ИИ-анализ, он не заменяет официальную экспертизу.",
        "This is an AI-assisted analysis and does not replace formal expert review.",
    ),
    "rec_final": (
        "Түпкілікті шешімді жобалау құжаттамасының ресми сараптамасында растаңыз.",
        "Окончательное решение подтвердите в ходе официальной экспертизы проектной документации.",
        "Confirm the final decision through formal expert review of the design documentation.",
    ),
    "tall_note": (
        " (шамамен 13 м-ден биік ғимарат)",
        " (здание выше примерно 13 м)",
        " (building taller than about 13 m)",
    ),
    "sub_corridor": ("дәліз", "коридор", "corridor"),
    "sub_door": ("есік", "дверь", "door"),
    "sub_dir": ("бағыт", "ориентация", "orientation"),
    "sub_high": ("көпқабатты ғимарат", "многоэтажное здание", "multi-storey building"),
    "unit_m": ("м", "м", "m"),
    # --- база нормативов -----------------------------------------------------------------
    "norms_title": ("Нормативтер базасы", "База нормативов", "Standards Library"),
    "norms_sub": (
        "RAG-пайплайнда қолданылатын нормативтік құжаттар мен талаптар анықтамалығы",
        "Справочник нормативных документов и требований, используемых в RAG-пайплайне",
        "Reference of the documents and provisions used by the RAG pipeline",
    ),
    "tab_docs": ("Құжаттар", "Документы", "Documents"),
    "tab_prov": ("Талаптар", "Требования", "Provisions"),
    "tab_test": ("Іздеуді тексеру", "Проверка поиска", "Retrieval test"),
    "search": ("Іздеу", "Поиск", "Search"),
    "filter_doc": ("Құжат бойынша сүзгі", "Фильтр по документу", "Filter by document"),
    "all_docs": ("Барлық құжаттар", "Все документы", "All documents"),
    "doc_scope": ("Қамту аясы", "Область применения", "Scope"),
    "clause_lbl": ("Бөлім", "Раздел", "Section"),
    "figure_lbl": ("Негізгі көрсеткіш", "Ключевой показатель", "Key figure"),
    "norms_note": (
        "Үзінділер оқу мақсатында жинақталған. Нақты жобада құжаттардың қолданыстағы ресми басылымын "
        "тексеріңіз (ҚР нормативтік құқықтық актілер тізілімі).",
        "Выдержки подготовлены в учебных целях. В реальном проекте сверяйте их с действующей официальной "
        "редакцией документов (реестр нормативных правовых актов РК).",
        "Excerpts are prepared for educational purposes. For a real project verify them against the current "
        "official edition (the RK register of normative legal acts).",
    ),
    "test_hint": (
        "Сұрауды енгізіп, retrieve_norms() қандай фрагменттерді қайтаратынын көріңіз.",
        "Введите запрос и посмотрите, какие фрагменты вернёт retrieve_norms().",
        "Enter a query to see which provisions retrieve_norms() returns.",
    ),
    "no_match": ("Ештеңе табылмады.", "Ничего не найдено.", "Nothing found."),
    "found_n": ("Табылды: {n}", "Найдено: {n}", "Found: {n}"),
    # --- история ----------------------------------------------------------------------------
    "hist_title": ("Тарих және есептер", "История и отчёты", "History & Reports"),
    "hist_sub": (
        "Орындалған тексерулер архиві және есептерді TXT / PDF форматында экспорттау",
        "Архив выполненных проверок и экспорт отчётов в форматах TXT / PDF",
        "Archive of completed checks and report export to TXT / PDF",
    ),
    "hist_note": (
        "Тарих ағымдағы сессияда сақталады. JSON арқылы сақтап, кейін қайта жүктеуге болады.",
        "История хранится в рамках текущей сессии. Её можно сохранить в JSON и загрузить позже.",
        "History lives in the current session. Save it as JSON and import it later.",
    ),
    "hist_empty": (
        "Тарих бос. Нормалар инспекторында алғашқы тексеруді орындаңыз.",
        "История пуста. Выполните первую проверку в Инспекторе норм.",
        "History is empty. Run your first check in the Norm Inspector.",
    ),
    "col_time": ("Уақыты", "Время", "Time"),
    "col_mode": ("Режим", "Режим", "Mode"),
    "col_verdict": ("Қорытынды", "Заключение", "Verdict"),
    "col_query": ("Сұрау", "Запрос", "Query"),
    "m_ai": ("ЖИ", "ИИ", "AI"),
    "m_demo": ("Демо", "Демо", "Demo"),
    "pick": ("Жазбаны таңдаңыз", "Выберите запись", "Select a record"),
    "exp_all": ("Барлық тарихты экспорттау", "Экспорт всей истории", "Export entire history"),
    "exp_one": ("Таңдалған жазба есебі", "Отчёт по выбранной записи", "Selected record report"),
    "json_dl": ("Тарихты жүктеу (.json)", "Скачать историю (.json)", "Download history (.json)"),
    "json_ul": ("Тарихты импорттау (.json)", "Импорт истории (.json)", "Import history (.json)"),
    "imp_btn": ("Импорттау", "Импортировать", "Import"),
    "imp_ok": ("Импортталды: {n}", "Импортировано записей: {n}", "Records imported: {n}"),
    "imp_bad": ("Файл форматы жарамсыз.", "Неверный формат файла.", "Invalid file format."),
    "delete": ("Жазбаны жою", "Удалить запись", "Delete record"),
    "clear": ("Тарихты тазалау", "Очистить историю", "Clear history"),
    "confirm_clear": ("Тазалауды растаймын", "Подтверждаю очистку", "I confirm clearing"),
    # --- отчёт ----------------------------------------------------------------------------------
    "rp_title": (
        "ҚР нормаларына сәйкестікті тексеру есебі",
        "Отчёт о проверке соответствия нормам РК",
        "Compliance inspection report",
    ),
    "rp_mode": ("Режим", "Режим", "Mode"),
    "rp_lang": ("Тексеру тілі", "Язык проверки", "Check language"),
    "rp_disc": (
        "Есеп анықтамалық сипатта. Нақты жобада нормативтік құжаттардың қолданыстағы ресми басылымын тексеріңіз.",
        "Отчёт носит справочный характер. В реальном проекте сверяйтесь с действующей официальной редакцией нормативных документов.",
        "This report is informational. For a real project verify against the current official edition of the standards.",
    ),
    # --- направления света -----------------------------------------------------------------------
    "dir_N": ("Солтүстік", "Север", "North"),
    "dir_NE": ("Солтүстік-шығыс", "Северо-восток", "North-east"),
    "dir_E": ("Шығыс", "Восток", "East"),
    "dir_SE": ("Оңтүстік-шығыс", "Юго-восток", "South-east"),
    "dir_S": ("Оңтүстік", "Юг", "South"),
    "dir_SW": ("Оңтүстік-батыс", "Юго-запад", "South-west"),
    "dir_W": ("Батыс", "Запад", "West"),
    "dir_NW": ("Солтүстік-батыс", "Северо-запад", "North-west"),
}


def t(key: str, **kw) -> str:
    s = S[key][LANG_IDX[L()]]
    return s.format(**kw) if kw else s


# --- шаблоны выявленных замечаний (kk, ru, en) ---------------------------------------------
FIND: Dict[str, Tuple[str, str, str]] = {
    "fire_missing": (
        "Көрші ғимаратқа дейінгі арақашықтық көрсетілмеген — тексеру мүмкін емес.",
        "Расстояние до соседнего здания не указано — проверка невозможна.",
        "Distance to the neighbouring building is not specified — the check cannot be performed.",
    ),
    "fire_ok": (
        "{a} және {b} дәрежелі ғимараттар үшін талап — кемінде {need} м; жобада {d} м. Талап орындалған.",
        "Для зданий степени {a} и {b} требуется не менее {need} м; в проекте {d} м. Требование выполнено.",
        "For degrees {a} and {b} at least {need} m is required; the design provides {d} m. Requirement met.",
    ),
    "fire_fail": (
        "{a} және {b} дәрежелі ғимараттар үшін талап — кемінде {need} м, ал жобада {d} м (жетіспейді: {short} м).",
        "Для зданий степени {a} и {b} требуется не менее {need} м, в проекте {d} м (не хватает {short} м).",
        "For degrees {a} and {b} at least {need} m is required, the design provides {d} m (shortfall {short} m).",
    ),
    "fire_fail_known": (
        "{k} дәрежелі ғимарат үшін {d} м арақашықтық көрші ғимараттың кез келген дәрежесінде жеткіліксіз (ең аз талап — {min} м).",
        "Для здания степени {k} расстояние {d} м недостаточно при любой степени соседнего здания (минимум — {min} м).",
        "For a degree-{k} building {d} m is insufficient for any neighbouring degree (minimum {min} m).",
    ),
    "fire_lt6": (
        "{d} м — отқа төзімділік дәрежесіне қарамастан ең аз талап (6 м) орындалмайды.",
        "{d} м — минимальное требование (6 м) не выполняется при любой степени огнестойкости.",
        "{d} m — the absolute minimum of 6 m is not met for any fire resistance degree.",
    ),
    "fire_ge15": (
        "{d} м — барлық отқа төзімділік дәрежелері үшін (6–15 м) жеткілікті.",
        "{d} м — достаточно для любых степеней огнестойкости (6–15 м).",
        "{d} m — sufficient for all fire resistance degrees (6–15 m).",
    ),
    "fire_partial_known": (
        "{k} дәрежелі ғимарат үшін {d} м арақашықтық көрші ғимарат дәрежесі {opts} болғанда ғана жеткілікті.",
        "Для здания степени {k} расстояние {d} м достаточно только при степени соседнего здания: {opts}.",
        "For a degree-{k} building {d} m is sufficient only if the neighbouring building is of degree {opts}.",
    ),
    "fire_partial_unknown": (
        "{d} м арақашықтық отқа төзімділік дәрежесіне байланысты жеткілікті немесе жеткіліксіз болуы мүмкін (талап 6–15 м).",
        "Расстояние {d} м может быть достаточным или недостаточным в зависимости от степени огнестойкости (требование 6–15 м).",
        "A distance of {d} m may or may not be sufficient depending on the fire resistance degrees (requirement 6–15 m).",
    ),
    "high_rise": (
        "{n} қабатты ғимаратқа қосымша өрт қауіпсіздігі талаптары қойылады (өрт сөндіру көліктерінің өтуі, түтінсіз баспалдақ торлары және т.б.).",
        "К {n}-этажному зданию предъявляются дополнительные требования пожарной безопасности (проезд пожарной техники, незадымляемые лестничные клетки и др.).",
        "A {n}-storey building is subject to additional fire safety requirements (fire engine access, smoke-free stairwells, etc.).",
    ),
    "ins_ok": (
        "Инсоляция ұзақтығы {h} сағ — талап (кемінде 2,5 сағ) орындалған.",
        "Продолжительность инсоляции {h} ч — требование (не менее 2,5 ч) выполнено.",
        "Insolation duration {h} h — the requirement (at least 2.5 h) is met.",
    ),
    "ins_fail": (
        "Инсоляция ұзақтығы {h} сағ, ал талап — кемінде 2,5 сағ (жетіспейді: {short} сағ).",
        "Продолжительность инсоляции {h} ч, при требовании не менее 2,5 ч (не хватает {short} ч).",
        "Insolation duration is {h} h against a requirement of at least 2.5 h (shortfall {short} h).",
    ),
    "ins_north": (
        "Терезелер тек солтүстікке бағытталған: мұндай пәтерлерде нормативтік инсоляция қамтамасыз етілмейді.",
        "Окна ориентированы только на север: нормативная инсоляция в таких квартирах не обеспечивается.",
        "Windows face north only: normative insolation cannot be provided in such apartments.",
    ),
    "ins_diag": (
        "{o} бағыты инсоляция бойынша шектеулі; инсоляциялық есеп міндетті.",
        "Ориентация {o} ограничена по инсоляции; необходим инсоляционный расчёт.",
        "The {o} orientation is limited for insolation; an insolation calculation is required.",
    ),
    "ins_dir_noh": (
        "Терезе бағыты — {o}: бағыт қолайлы, бірақ инсоляция ұзақтығы есептелмеген.",
        "Ориентация окон — {o}: направление благоприятное, но продолжительность инсоляции не рассчитана.",
        "Window orientation is {o}: favourable, but the insolation duration has not been calculated.",
    ),
    "ins_none": (
        "Инсоляция ұзақтығы да, терезе бағыты да көрсетілмеген.",
        "Не указаны ни продолжительность инсоляции, ни ориентация окон.",
        "Neither the insolation duration nor the window orientation is specified.",
    ),
    "evac_missing": (
        "Дәліз бен эвакуациялық есіктің ені көрсетілмеген.",
        "Ширина коридора и эвакуационной двери не указана.",
        "The corridor and evacuation door widths are not specified.",
    ),
    "corr_ok": (
        "Дәліз ені {w} м — талап (кемінде 1,2 м) орындалған.",
        "Ширина коридора {w} м — требование (не менее 1,2 м) выполнено.",
        "Corridor width {w} m — the requirement (at least 1.2 m) is met.",
    ),
    "corr_fail": (
        "Дәліз ені {w} м, ал талап — кемінде 1,2 м (жетіспейді: {short} м).",
        "Ширина коридора {w} м при требовании не менее 1,2 м (не хватает {short} м).",
        "Corridor width is {w} m against at least 1.2 m required (shortfall {short} m).",
    ),
    "door_ok": (
        "Эвакуациялық есік ені {w} м — талап (кемінде 0,8 м) орындалған.",
        "Ширина эвакуационной двери {w} м — требование (не менее 0,8 м) выполнено.",
        "Evacuation door width {w} m — the requirement (at least 0.8 m) is met.",
    ),
    "door_fail": (
        "Эвакуациялық есік ені {w} м, ал талап — кемінде 0,8 м.",
        "Ширина эвакуационной двери {w} м при требовании не менее 0,8 м.",
        "Evacuation door width is {w} m against at least 0.8 m required.",
    ),
    "height_missing": (
        "Тұрғын бөлмелердің жарықтағы биіктігі көрсетілмеген.",
        "Высота жилых помещений в свету не указана.",
        "The clear height of habitable rooms is not specified.",
    ),
    "height_ok": (
        "Биіктік {h} м — талап (кемінде 2,7 м) орындалған.",
        "Высота {h} м — требование (не менее 2,7 м) выполнено.",
        "Height {h} m — the requirement (at least 2.7 m) is met.",
    ),
    "height_fail": (
        "Биіктік {h} м, ал талап — кемінде 2,7 м (жетіспейді: {short} м).",
        "Высота {h} м при требовании не менее 2,7 м (не хватает {short} м).",
        "Height is {h} m against at least 2.7 m required (shortfall {short} m).",
    ),
    "park_missing": (
        "Автотұрақтан тұрғын үй терезелеріне дейінгі арақашықтық көрсетілмеген.",
        "Расстояние от парковки до окон жилого дома не указано.",
        "The distance from the parking area to residential windows is not specified.",
    ),
    "park_ok_cars": (
        "{n} көлікке талап — кемінде {need} м; жобада {d} м. Орындалған.",
        "Для {n} машин требуется не менее {need} м; в проекте {d} м. Выполнено.",
        "For {n} cars at least {need} m is required; the design provides {d} m. Met.",
    ),
    "park_fail_cars": (
        "{n} көлікке талап — кемінде {need} м, ал жобада {d} м (жетіспейді: {short} м).",
        "Для {n} машин требуется не менее {need} м, в проекте {d} м (не хватает {short} м).",
        "For {n} cars at least {need} m is required, the design provides {d} m (shortfall {short} m).",
    ),
    "park_lt10": (
        "{d} м — ең аз талап (10 м) орындалмайды.",
        "{d} м — минимальное требование (10 м) не выполняется.",
        "{d} m — the minimum requirement of 10 m is not met.",
    ),
    "park_10_15": (
        "{d} м — 10 көлікке дейін жеткілікті, ал 11–50 көлікке 15 м қажет.",
        "{d} м — достаточно для парковки до 10 машин, для 11–50 машин требуется 15 м.",
        "{d} m — sufficient for up to 10 cars; 11–50 cars require 15 m.",
    ),
    "park_ok": (
        "{d} м — 50 көлікке дейінгі тұрақ үшін жеткілікті.",
        "{d} м — достаточно для парковки до 50 машин.",
        "{d} m — sufficient for parking of up to 50 cars.",
    ),
    "drive_missing": (
        "Өтпе жолдың ені көрсетілмеген.",
        "Ширина проезда не указана.",
        "The fire access width is not specified.",
    ),
    "drive_ok": (
        "Өтпе ені {w} м — талап (кемінде {need} м){note} орындалған.",
        "Ширина проезда {w} м — требование (не менее {need} м){note} выполнено.",
        "Access width {w} m — the requirement (at least {need} m){note} is met.",
    ),
    "drive_fail": (
        "Өтпе ені {w} м, ал талап — кемінде {need} м{note}.",
        "Ширина проезда {w} м при требовании не менее {need} м{note}.",
        "Access width is {w} m against at least {need} m required{note}.",
    ),
    "nodata": (
        "Сұраудан тексеруге болатын тақырып не параметр анықталмады.",
        "В запросе не обнаружено тем или параметров, пригодных для проверки.",
        "No checkable topic or parameter was detected in the request.",
    ),
}

REC: Dict[str, Tuple[str, str, str]] = {
    "fire_missing": (
        "Ғимараттар арасындағы нақты арақашықтықты (м) және отқа төзімділік дәрежелерін көрсетіңіз.",
        "Укажите фактическое расстояние между зданиями (м) и степени огнестойкости.",
        "Provide the actual distance between buildings (m) and the fire resistance degrees.",
    ),
    "fire_fail": (
        "Арақашықтықты {need} м-ге дейін ұлғайтыңыз, не отқа төзімділік дәрежесін арттырыңыз, не өртке қарсы қабырға (брандмауэр) мен нормада қарастырылған өтемақы шараларын қолданыңыз.",
        "Увеличьте расстояние до {need} м, повысьте степень огнестойкости либо примените противопожарную стену (брандмауэр) и иные компенсирующие меры, предусмотренные нормами.",
        "Increase the distance to {need} m, raise the fire resistance degree, or apply a fire wall and other compensating measures permitted by the standards.",
    ),
    "fire_fail_known": (
        "Арақашықтықты кемінде {min} м-ге дейін ұлғайтыңыз немесе отқа төзімділік дәрежесін арттырыңыз.",
        "Увеличьте расстояние минимум до {min} м либо повысьте степень огнестойкости.",
        "Increase the distance to at least {min} m or raise the fire resistance degree.",
    ),
    "fire_lt6": (
        "Арақашықтықты кем дегенде 6 м-ге дейін ұлғайтып, дәрежелерді нақтылаңыз.",
        "Увеличьте расстояние минимум до 6 м и уточните степени огнестойкости.",
        "Increase the distance to at least 6 m and clarify the fire resistance degrees.",
    ),
    "fire_partial": (
        "Екі ғимараттың да отқа төзімділік дәрежесін (I–V) көрсетіп, қайта тексеріңіз.",
        "Укажите степени огнестойкости обоих зданий (I–V) и повторите проверку.",
        "Specify the fire resistance degrees (I–V) of both buildings and re-run the check.",
    ),
    "high_rise": (
        "Қосымша талаптарды өрт қауіпсіздігі нормасы бойынша жеке тексеріңіз.",
        "Проверьте дополнительные требования отдельно по нормам пожарной безопасности.",
        "Check the additional requirements separately against the fire safety standard.",
    ),
    "ins_fail": (
        "Терезелердің бағытын өзгертіңіз, пәтерлердің жоспарлау шешімін немесе ғимараттың орналасуын қайта қарап, инсоляциялық есепті қайталаңыз.",
        "Измените ориентацию окон, пересмотрите планировку квартир или размещение здания и повторите инсоляционный расчёт.",
        "Change the window orientation, revise the apartment layout or the building position and repeat the insolation calculation.",
    ),
    "ins_north": (
        "Тұрғын бөлмелердің кемінде біреуін оңтүстік, шығыс немесе батыс бағытқа бұрыңыз.",
        "Сориентируйте хотя бы одну жилую комнату на юг, восток или запад.",
        "Orient at least one habitable room to the south, east or west.",
    ),
    "ins_diag": (
        "Инсоляциялық есеп жүргізіп, 2,5 сағ талабын растаңыз.",
        "Выполните инсоляционный расчёт и подтвердите требование 2,5 ч.",
        "Run an insolation calculation and confirm the 2.5 h requirement.",
    ),
    "ins_dir_noh": (
        "Көршілес ғимараттардың көлеңкесін ескеріп, инсоляция ұзақтығын есептеңіз.",
        "Рассчитайте продолжительность инсоляции с учётом затенения соседними зданиями.",
        "Calculate the insolation duration taking shading by neighbouring buildings into account.",
    ),
    "ins_none": (
        "Терезе бағытын және есептелген инсоляция ұзақтығын (сағ) көрсетіңіз.",
        "Укажите ориентацию окон и рассчитанную продолжительность инсоляции (ч).",
        "Provide the window orientation and the calculated insolation duration (h).",
    ),
    "evac_missing": (
        "Дәліздің және эвакуациялық есіктің жарықтағы енін (м) көрсетіңіз.",
        "Укажите ширину коридора и эвакуационной двери в свету (м).",
        "Provide the clear width of the corridor and the evacuation door (m).",
    ),
    "corr_fail": (
        "Дәліздің енін кемінде 1,2 м-ге дейін ұлғайтыңыз (адам саны көп болса — есеппен одан да көп).",
        "Увеличьте ширину коридора минимум до 1,2 м (при большом числе людей — по расчёту, больше).",
        "Widen the corridor to at least 1.2 m (more, by calculation, for higher occupancy).",
    ),
    "door_fail": (
        "Есіктің жарықтағы енін кемінде 0,8 м-ге дейін ұлғайтыңыз.",
        "Увеличьте ширину двери в свету минимум до 0,8 м.",
        "Increase the clear door width to at least 0.8 m.",
    ),
    "height_missing": (
        "Еден мен төбе арасындағы биіктікті (м) көрсетіңіз.",
        "Укажите высоту от пола до потолка (м).",
        "Provide the floor-to-ceiling height (m).",
    ),
    "height_fail": (
        "Жарықтағы биіктікті кемінде 2,7 м-ге дейін көтеріңіз (қабат биіктігін немесе төбе құрылымын қайта қараңыз).",
        "Увеличьте высоту в свету минимум до 2,7 м (пересмотрите высоту этажа или конструкцию перекрытия).",
        "Raise the clear height to at least 2.7 m (revise the storey height or the ceiling build-up).",
    ),
    "park_missing": (
        "Арақашықтықты (м) және тұрақтағы көлік санын көрсетіңіз.",
        "Укажите расстояние (м) и количество машин на парковке.",
        "Provide the distance (m) and the number of parked cars.",
    ),
    "park_fail_cars": (
        "Тұрақты терезелерден кемінде {need} м-ге алыстатыңыз немесе көлік санын азайтыңыз.",
        "Отодвиньте парковку от окон минимум до {need} м либо сократите число машин.",
        "Move the parking at least {need} m away from the windows or reduce the number of cars.",
    ),
    "park_lt10": (
        "Тұрақты тұрғын үй терезелерінен кемінде 10 м-ге алыстатыңыз.",
        "Отодвиньте парковку от окон жилого дома минимум на 10 м.",
        "Move the parking at least 10 m away from residential windows.",
    ),
    "park_10_15": (
        "Тұрақтағы көлік санын көрсетіп, қайта тексеріңіз.",
        "Укажите количество машин и повторите проверку.",
        "Specify the number of cars and re-run the check.",
    ),
    "drive_missing": (
        "Өрт сөндіру көліктеріне арналған өтпенің енін (м) көрсетіңіз.",
        "Укажите ширину проезда для пожарной техники (м).",
        "Provide the width of the fire engine access (m).",
    ),
    "drive_fail": (
        "Өтпе енін кемінде {need} м-ге дейін ұлғайтыңыз.",
        "Увеличьте ширину проезда минимум до {need} м.",
        "Widen the access to at least {need} m.",
    ),
    "nodata": (
        "Өрт қауіпсіздігі, инсоляция, эвакуация, қабат биіктігі немесе автотұрақ бойынша нақты сандық мәндерді көрсетіңіз.",
        "Укажите конкретные числовые значения по пожарной безопасности, инсоляции, эвакуации, высоте этажа или парковке.",
        "Provide concrete numeric values for fire safety, insolation, evacuation, storey height or parking.",
    ),
}
REC_MAP = {
    "fire_partial_known": "fire_partial",
    "fire_partial_unknown": "fire_partial",
    "park_fail_cars": "park_fail_cars",
}


def tf(table: Dict[str, Tuple[str, str, str]], key: str, **kw) -> str:
    s = table[key][LANG_IDX[L()]]
    return s.format(**kw) if kw else s


# =============================================================================
# 3. НОРМАТИВНАЯ БАЗА (RAG knowledge base)
# =============================================================================
DOCS: Dict[str, Dict] = {
    "sp_3_01": {
        "code": ("ҚР ЕЖ 3.01-101-2013", "СП РК 3.01-101-2013", "SP RK 3.01-101-2013"),
        "title": (
            "Қалалық және ауылдық елді мекендерді жоспарлау және салу",
            "Градостроительство. Планировка и застройка городских и сельских населённых пунктов",
            "Urban planning. Planning and development of urban and rural settlements",
        ),
        "scope": (
            "Қала құрылысы, аумақты жоспарлау, санитарлық үзілістер, автотұрақтар",
            "Градостроительные требования, планировка территории, санитарные разрывы, парковки",
            "Urban planning, site layout, sanitary separations, parking areas",
        ),
    },
    "sn_2_02": {
        "code": ("ҚР ҚН 2.02-01-2023", "СН РК 2.02-01-2023", "SN RK 2.02-01-2023"),
        "title": (
            "Ғимараттар мен құрылыстардың өрт қауіпсіздігі",
            "Пожарная безопасность зданий и сооружений",
            "Fire safety of buildings and structures",
        ),
        "scope": (
            "Өртке қарсы арақашықтықтар, эвакуация, өрт сөндіру техникасының өтуі",
            "Противопожарные расстояния, эвакуация, проезды пожарной техники",
            "Fire separation distances, evacuation, fire engine access",
        ),
    },
    "sp_3_02": {
        "code": ("ҚР ЕЖ 3.02-101-2012", "СП РК 3.02-101-2012", "SP RK 3.02-101-2012"),
        "title": (
            "Көппәтерлі тұрғын үйлер",
            "Здания жилые многоквартирные",
            "Multi-apartment residential buildings",
        ),
        "scope": (
            "Тұрғын үй-жайлардың параметрлері, қабат биіктігі, жоспарлау шешімдері",
            "Параметры жилых помещений, высота этажа, планировочные решения",
            "Habitable room parameters, storey height, layout solutions",
        ),
    },
    "san": {
        "code": (
            "Санитариялық талаптар",
            "Санитарные требования",
            "Sanitary requirements",
        ),
        "title": (
            "Тұрғын үй-жайларға қойылатын санитариялық-эпидемиологиялық талаптар",
            "Санитарно-эпидемиологические требования к жилым помещениям",
            "Sanitary and epidemiological requirements for residential premises",
        ),
        "scope": (
            "Инсоляция, санитарлық үзілістер, тұрғын орта",
            "Инсоляция, санитарные разрывы, жилая среда",
            "Insolation, sanitary separations, residential environment",
        ),
    },
}

NORMS: List[Dict] = [
    {
        "id": "fire_distance",
        "docs": ["sn_2_02", "sp_3_01"],
        "topic": (
            "Ғимараттар арасындағы өртке қарсы арақашықтық",
            "Противопожарные расстояния между зданиями",
            "Fire separation distances between buildings",
        ),
        "clause": (
            "Ғимараттар мен құрылыстар арасындағы өртке қарсы ара қашықтықтар (кесте)",
            "Противопожарные расстояния между зданиями и сооружениями (таблица)",
            "Fire separation distances between buildings and structures (table)",
        ),
        "text": (
            "Ғимараттар арасындағы өртке қарсы арақашықтық олардың отқа төзімділік дәрежесіне байланысты "
            "6 м-ден 15 м-ге дейін қабылданады: I–II және I–II — 6 м; I–II және III — 8 м; III және III — 8 м; "
            "I–II және IV–V — 10 м; III және IV–V — 10 м; IV–V және IV–V — 15 м. Арақашықтықты азайту үшін "
            "өртке қарсы қабырға (брандмауэр) және нормада қарастырылған басқа шаралар қолданылуы мүмкін.",
            "Противопожарное расстояние между зданиями принимается в зависимости от степени их огнестойкости "
            "и составляет от 6 до 15 м: I–II и I–II — 6 м; I–II и III — 8 м; III и III — 8 м; I–II и IV–V — 10 м; "
            "III и IV–V — 10 м; IV–V и IV–V — 15 м. Для сокращения расстояний могут применяться "
            "противопожарные стены (брандмауэры) и иные компенсирующие меры, предусмотренные нормами.",
            "The fire separation distance depends on the fire resistance degree of the buildings and ranges "
            "from 6 to 15 m: I–II with I–II — 6 m; I–II with III — 8 m; III with III — 8 m; I–II with IV–V — 10 m; "
            "III with IV–V — 10 m; IV–V with IV–V — 15 m. Fire walls and other compensating measures permitted "
            "by the standards may be used to reduce the distances.",
        ),
        "figure": ("6–15", "m"),
        "kw": [
            "өрт", "өртке қарсы", "отқа төзімділік", "арақашықтық", "ара қашықтық", "көрші ғимарат",
            "брандмауэр", "пожар", "противопожар", "огнестойк", "разрыв", "расстояние между",
            "fire", "separation", "fire resistance", "distance between", "firewall", "fire wall",
        ],
    },
    {
        "id": "insolation",
        "docs": ["sp_3_01", "san"],
        "topic": (
            "Тұрғын бөлмелердің инсоляциясы",
            "Инсоляция жилых помещений",
            "Insolation of habitable rooms",
        ),
        "clause": (
            "Тұрғын үй мен аумақтың инсоляциясы",
            "Инсоляция жилых зданий и территории",
            "Insolation of residential buildings and territories",
        ),
        "text": (
            "Тұрғын бөлмелердің үздіксіз инсоляция ұзақтығы ҚР оңтүстік және орталық аймақтары үшін кемінде "
            "2,5 сағат болуы тиіс. Терезелері тек солтүстікке бағытталған пәтерлерді жобалауға жол берілмейді; "
            "солтүстік-шығыс және солтүстік-батыс бағыттарда инсоляциялық есеп міндетті.",
            "Продолжительность непрерывной инсоляции жилых помещений для южной и центральной зон РК должна "
            "составлять не менее 2,5 ч. Не допускается проектирование квартир с окнами, ориентированными "
            "только на север; при ориентации на северо-восток и северо-запад инсоляционный расчёт обязателен.",
            "The continuous insolation of habitable rooms in the southern and central zones of Kazakhstan "
            "must be at least 2.5 hours. Apartments with windows facing north only are not permitted; for "
            "north-east and north-west orientations an insolation calculation is mandatory.",
        ),
        "figure": ("≥ 2,5", "h"),
        "kw": [
            "инсоляц", "күн сәулесі", "күн сәуле", "солтүстік", "оңтүстік", "бағыт", "табиғи жарық",
            "жарықтандыру", "ориентац", "инсол", "солнечн", "север", "insolation", "sunlight", "orientation",
            "north", "south", "daylight",
        ],
    },
    {
        "id": "evacuation",
        "docs": ["sn_2_02"],
        "topic": (
            "Эвакуациялық жолдар мен шығыстардың ені",
            "Ширина эвакуационных путей и выходов",
            "Width of evacuation routes and exits",
        ),
        "clause": (
            "Эвакуациялық жолдар және эвакуациялық шығыстар",
            "Эвакуационные пути и эвакуационные выходы",
            "Evacuation routes and evacuation exits",
        ),
        "text": (
            "Эвакуациялық жолдардың (дәліздердің) ені кемінде 1,2 м болуы тиіс; эвакуацияланатын адам саны көп "
            "болған жағдайда ені есеппен ұлғайтылады. Эвакуациялық шығыс есіктерінің жарықтағы ені кемінде "
            "0,8 м. Жол бойында ені мен биіктігін азайтатын бөгеттер болмауы тиіс.",
            "Ширина эвакуационных путей (коридоров) должна быть не менее 1,2 м; при большом числе эвакуируемых "
            "ширина увеличивается по расчёту. Ширина эвакуационных дверей в свету — не менее 0,8 м. На путях "
            "эвакуации не допускаются препятствия, уменьшающие ширину и высоту прохода.",
            "The width of evacuation routes (corridors) must be at least 1.2 m and is increased by calculation "
            "for high occupancy. Evacuation exit doors must have a clear width of at least 0.8 m. No obstacles "
            "reducing the width or height of the route are permitted.",
        ),
        "figure": ("≥ 1,2", "m"),
        "kw": [
            "эвакуац", "дәліз", "коридор", "эвакуациялық шығыс", "есік", "қашу жол", "двер", "путь эвакуации",
            "evacuation", "corridor", "exit", "door", "egress",
        ],
    },
    {
        "id": "ceiling_height",
        "docs": ["sp_3_02"],
        "topic": (
            "Тұрғын үй қабатының биіктігі",
            "Высота этажа жилого здания",
            "Storey height of residential buildings",
        ),
        "clause": (
            "Көппәтерлі тұрғын үйлердің үй-жайларына қойылатын талаптар",
            "Требования к помещениям многоквартирных жилых зданий",
            "Requirements for rooms of multi-apartment residential buildings",
        ),
        "text": (
            "Тұрғын бөлмелер мен асүйдің еден мен төбе арасындағы биіктігі (жарықтағы) кемінде 2,7 м болуы тиіс.",
            "Высота жилых комнат и кухни от пола до потолка (в свету) должна быть не менее 2,7 м.",
            "The clear floor-to-ceiling height of habitable rooms and kitchens must be at least 2.7 m.",
        ),
        "figure": ("≥ 2,7", "m"),
        "kw": [
            "биік", "төбе", "еден мен төбе", "қабат биіктігі", "потол", "высота этаж", "высота помещ",
            "жарықтағы", "в свету", "ceiling", "clear height", "storey height", "floor height",
        ],
    },
    {
        "id": "parking",
        "docs": ["sp_3_01", "san"],
        "topic": (
            "Автотұрақтардан тұрғын үй терезелеріне дейінгі арақашықтық",
            "Расстояние от парковок до окон жилых домов",
            "Distance from parking areas to residential windows",
        ),
        "clause": (
            "Автотұрақтарды орналастыру, санитарлық үзіліс",
            "Размещение автостоянок, санитарные разрывы",
            "Siting of parking areas, sanitary separations",
        ),
        "text": (
            "Ашық автотұрақтардан тұрғын үйлердің терезелеріне дейінгі арақашықтық көлік санына байланысты "
            "кемінде 10–15 м: 10 көлікке дейін — 10 м, 11–50 көлік — 15 м. Көлік саны артқан сайын арақашықтық "
            "ұлғаяды (50-ден көп болса — 25 м және одан артық, нақтылау қажет).",
            "Расстояние от открытых автостоянок до окон жилых домов — не менее 10–15 м в зависимости от числа "
            "машин: до 10 машин — 10 м, 11–50 машин — 15 м. С ростом числа машин расстояние увеличивается "
            "(свыше 50 — 25 м и более, требуется уточнение).",
            "The distance from open parking areas to residential windows is at least 10–15 m depending on the "
            "number of cars: up to 10 cars — 10 m, 11–50 cars — 15 m. The distance grows with the number of cars "
            "(over 50 — 25 m or more, to be verified).",
        ),
        "figure": ("10–15", "m"),
        "kw": [
            "тұрақ", "автотұрақ", "парковк", "стоянк", "көлік", "машин", "автомобил", "терезеге дейін",
            "parking", "car park", "cars", "vehicle",
        ],
    },
    {
        "id": "fire_access",
        "docs": ["sn_2_02"],
        "topic": (
            "Өрт сөндіру техникасының өтуі",
            "Проезд пожарной техники",
            "Fire engine access",
        ),
        "clause": (
            "Өрт сөндіру көліктеріне арналған өтпелер мен кіреберістер",
            "Проезды и подъезды для пожарных автомобилей",
            "Access roads and approaches for fire engines",
        ),
        "text": (
            "Өрт сөндіру көліктерінің өтпе жолының ені кемінде 3,5 м; биіктігі 13 м-ден асатын (шамамен "
            "4 қабаттан жоғары) ғимараттарға өтпе ені кемінде 4,2 м болуы тиіс. Биік және көпқабатты "
            "ғимараттарға қосымша талаптар қойылады.",
            "Ширина проезда для пожарных автомобилей — не менее 3,5 м; к зданиям высотой более 13 м "
            "(примерно выше 4 этажей) — не менее 4,2 м. К высотным и многоэтажным зданиям предъявляются "
            "дополнительные требования.",
            "The fire engine access width must be at least 3.5 m; for buildings taller than 13 m (roughly above "
            "4 storeys) at least 4.2 m. Tall and multi-storey buildings are subject to additional requirements.",
        ),
        "figure": ("≥ 3,5", "m"),
        "kw": [
            "өрт сөндіру", "өтпе", "өту жолы", "проезд", "подъезд", "өрт көлігі", "көпқабатты", "биік ғимарат",
            "жол ені", "пожарн", "fire truck", "fire access", "driveway", "fire lane", "fire engine", "high-rise",
        ],
    },
]
NORMS_BY_ID = {n["id"]: n for n in NORMS}


def nf(obj: Dict, field: str) -> str:
    """Поле записи на текущем языке."""
    return obj[field][LANG_IDX[L()]]


def retrieve_norms(query: str, hints: Optional[set] = None, top_k: int = 4) -> List[Dict]:
    """
    Retriever: ищет релевантные пункты базы по ключевым словам запроса (kk / ru / en).
    hints — темы, подразумеваемые введёнными параметрами (повышают релевантность).
    Возвращает: [{'id', 'score', 'matched'}, ...] по убыванию релевантности.
    """
    q = (query or "").lower()
    hints = hints or set()
    scored = []
    for norm in NORMS:
        matched = [kw for kw in norm["kw"] if kw in q]
        score = len(matched) + (3 if norm["id"] in hints else 0)
        if score > 0:
            scored.append({"id": norm["id"], "score": score, "matched": matched})
    scored.sort(key=lambda r: r["score"], reverse=True)
    if not scored:
        return []
    threshold = max(1.0, scored[0]["score"] * 0.34)
    return [r for r in scored if r["score"] >= threshold][:top_k]


# =============================================================================
# 4. ПАРАМЕТРЫ, ИЗВЛЕЧЕНИЕ ИЗ ТЕКСТА, ПРАВИЛОВЫЙ АНАЛИЗ
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


PARAM_LABEL_KEY = {
    "floors": "f_floors",
    "neighbor_distance": "f_distance",
    "orientation": "f_orient",
    "own_degree": "f_own",
    "neighbor_degree": "f_nb",
    "corridor_width": "f_corr",
    "door_width": "f_door",
    "floor_height": "f_height",
    "parking_distance": "f_park",
    "parking_cars": "f_cars",
    "insolation_hours": "f_hours",
    "driveway_width": "f_drive",
}

NUM_UNIT_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(сағат\w*|сағ\b|час\w*|ч\b|hours?\b|hrs?\b|h\b|"
    r"метр\w*|metres?\b|meters?\b|м\b|m\b)",
    re.IGNORECASE,
)
FLOORS_RE = re.compile(
    r"(\d+)\s*[-–]?\s*(?:қабатты|қабат|этажн\w*|этаж\w*|storeys?|stories|story|floors?)"
)
CARS_RE = re.compile(r"(\d+)\s*(?:автокөлік|көлік|машин\w*|автомобил\w*|cars?\b|vehicles?\b)")
DEGREE_RE = re.compile(
    r"\b(IV|V|I{1,3})\s*[-–]?\s*(?i:дәреж\w*|степен\w*|degree|class|rating)"
    r"|(?i:fire[\s-]*resistance(?:\s+(?:degree|rating|class))?|degree|rating|"
    r"степен\w*(?:\s+огнестойкост\w*)?|дәреже\w*)\s*[:\-]?\s*(IV|V|I{1,3})\b"
)
BOTH_RE = re.compile(
    r"екі\s+ғимарат\s+та|екеуі\s+де|екеуінің\s+де|\bобе\b|\bоба\b|both\s+buildings", re.IGNORECASE
)
ORIENT_TRIGGER = re.compile(r"терез|бағыт|қараған|қарайды|фасад|окн|ориентац|window|orient|\bfac(?:es|ing)\b")
ORIENT_PATTERNS = [
    ("NE", r"солтүстік[\s-]*шығыс|северо[\s-]*восток|north[\s-]*east"),
    ("NW", r"солтүстік[\s-]*батыс|северо[\s-]*запад|north[\s-]*west"),
    ("SE", r"оңтүстік[\s-]*шығыс|юго[\s-]*восток|south[\s-]*east"),
    ("SW", r"оңтүстік[\s-]*батыс|юго[\s-]*запад|south[\s-]*west"),
    ("N", r"солтүстік|север|\bnorth"),
    ("S", r"оңтүстік|\bюг|южн|\bsouth"),
    ("E", r"шығысқа|шығыс\s+бағыт|восток|восточн|\beast"),
    ("W", r"батысқа|батыс\s+бағыт|запад|западн|\bwest"),
]
CATEGORY_KEYS = {
    "parking": ["тұрақ", "автотұр", "парковк", "стоянк", "parking", "car park"],
    "corridor": ["дәліз", "коридор", "corridor", "hallway"],
    "door": ["есік", "двер", "door", "эвакуациялық шығыс", "exit"],
    "height": ["биік", "высот", "төбе", "потол", "height", "ceiling"],
    "driveway": ["өтпе", "өту жолы", "проезд", "подъезд", "driveway", "fire access", "fire lane", "өрт сөндіру", "пожарн"],
    "distance": ["арақашықтық", "ара қашықтық", "қашықтық", "аралық", "расстоя", "разрыв", "distance", "separation", "spacing", "gap"],
}
CATEGORY_FIELD = {
    "distance": "neighbor_distance",
    "parking": "parking_distance",
    "corridor": "corridor_width",
    "door": "door_width",
    "height": "floor_height",
    "driveway": "driveway_width",
}


def _classify(segment: str, unit: str) -> Optional[str]:
    """Определяет, к какому параметру относится число, по ближайшему ключевому слову."""
    if unit.lower().startswith(("сағ", "час", "ч", "h")):
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
    """Извлекает числовые параметры, ориентацию и степени огнестойкости из свободного текста."""
    p = Params()
    low = (text or "").lower()

    m = FLOORS_RE.search(low)
    if m:
        p.floors = int(m.group(1))
    m = CARS_RE.search(low)
    if m:
        p.parking_cars = int(m.group(1))

    prev_end = 0
    for m in NUM_UNIT_RE.finditer(low):
        value = float(m.group(1).replace(",", "."))
        unit = m.group(2)
        category = _classify(low[prev_end:m.start()], unit)
        if category is None:
            category = _classify(low[m.end():m.end() + 30], unit)
        prev_end = m.end()
        if category == "hours":
            if not p.insolation_hours:
                p.insolation_hours = value
        elif category in CATEGORY_FIELD:
            attr = CATEGORY_FIELD[category]
            if not getattr(p, attr):
                setattr(p, attr, value)

    if ORIENT_TRIGGER.search(low):
        for code, pattern in ORIENT_PATTERNS:
            if re.search(pattern, low):
                p.orientation = code
                break

    degrees = [m.group(1) or m.group(2) for m in DEGREE_RE.finditer((text or "").replace("І", "I"))]
    if len(degrees) >= 2:
        p.own_degree, p.neighbor_degree = degrees[0], degrees[1]
    elif len(degrees) == 1:
        p.own_degree = degrees[0]
        if BOTH_RE.search(low):
            p.neighbor_degree = degrees[0]
    return p


def merge_params(form: Params, extracted: Params) -> Params:
    """Значения формы приоритетнее; пустые поля заполняются из текста."""
    merged = Params()
    for f in fields(Params):
        v = getattr(form, f.name)
        setattr(merged, f.name, v if v else getattr(extracted, f.name))
    return merged


def implied_topics(p: Params) -> set:
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


def has_any_param(p: Params) -> bool:
    return any(bool(getattr(p, f.name)) for f in fields(Params))


def fmt(x, lang: Optional[str] = None) -> str:
    lang = lang or L()
    if isinstance(x, float):
        s = f"{round(x, 2):g}"
        return s if lang == "en" else s.replace(".", ",")
    return str(x)


def required_fire_distance(a: str, b: str) -> int:
    group = {"I": 1, "II": 1, "III": 2, "IV": 3, "V": 3}
    table = {(1, 1): 6, (1, 2): 8, (1, 3): 10, (2, 2): 8, (2, 3): 10, (3, 3): 15}
    return table[tuple(sorted((group[a], group[b])))]


def analyze(p: Params, active: set) -> Dict:
    """
    Правиловый анализ (демо-режим и перекрёстная проверка).
    Находки языконезависимы: {'code', 'level', 'topic', 'sub', 'args'} — текст подставляется при показе.
    """
    active = set(active) | implied_topics(p)
    findings: List[Dict] = []

    def add(code, level, topic, sub="", **args):
        findings.append({"code": code, "level": level, "topic": topic, "sub": sub, "args": args})

    if "fire_distance" in active:
        d, a, b = p.neighbor_distance, p.own_degree, p.neighbor_degree
        if not d:
            add("fire_missing", "warning", "fire_distance")
        elif a and b:
            need = required_fire_distance(a, b)
            if d >= need:
                add("fire_ok", "ok", "fire_distance", a=a, b=b, need=need, d=d)
            else:
                add("fire_fail", "error", "fire_distance", a=a, b=b, need=need, d=d, short=round(need - d, 2))
        elif d < 6:
            add("fire_lt6", "error", "fire_distance", d=d)
        elif d >= 15:
            add("fire_ge15", "ok", "fire_distance", d=d)
        else:
            known = a or b
            if known:
                ok_degrees = [x for x in DEGREES[1:] if required_fire_distance(known, x) <= d]
                if ok_degrees:
                    add("fire_partial_known", "warning", "fire_distance", k=known, d=d, opts=", ".join(ok_degrees))
                else:
                    min_need = min(required_fire_distance(known, x) for x in DEGREES[1:])
                    add("fire_fail_known", "error", "fire_distance", k=known, d=d, min=min_need)
            else:
                add("fire_partial_unknown", "warning", "fire_distance", d=d)
        if p.floors >= 10:
            add("high_rise", "warning", "fire_distance", sub="sub_high", n=p.floors)

    if "insolation" in active:
        h, o = p.insolation_hours, p.orientation
        if h:
            if h >= 2.5:
                add("ins_ok", "ok", "insolation", h=h)
            else:
                add("ins_fail", "error", "insolation", h=h, short=round(2.5 - h, 2))
        if o == "N":
            add("ins_north", "error", "insolation", sub="sub_dir")
        elif o in ("NE", "NW"):
            add("ins_diag", "warning", "insolation", sub="sub_dir", o=("dir", o))
        elif o and not h:
            add("ins_dir_noh", "warning", "insolation", sub="sub_dir", o=("dir", o))
        if not h and not o:
            add("ins_none", "warning", "insolation")

    if "evacuation" in active:
        if not p.corridor_width and not p.door_width:
            add("evac_missing", "warning", "evacuation")
        if p.corridor_width:
            if p.corridor_width >= 1.2:
                add("corr_ok", "ok", "evacuation", sub="sub_corridor", w=p.corridor_width)
            else:
                add("corr_fail", "error", "evacuation", sub="sub_corridor", w=p.corridor_width,
                    short=round(1.2 - p.corridor_width, 2))
        if p.door_width:
            if p.door_width >= 0.8:
                add("door_ok", "ok", "evacuation", sub="sub_door", w=p.door_width)
            else:
                add("door_fail", "error", "evacuation", sub="sub_door", w=p.door_width)

    if "ceiling_height" in active:
        h = p.floor_height
        if not h:
            add("height_missing", "warning", "ceiling_height")
        elif h >= 2.7:
            add("height_ok", "ok", "ceiling_height", h=h)
        else:
            add("height_fail", "error", "ceiling_height", h=h, short=round(2.7 - h, 2))

    if "parking" in active:
        d, cars = p.parking_distance, p.parking_cars
        if not d:
            add("park_missing", "warning", "parking")
        elif cars:
            need = 10 if cars <= 10 else 15 if cars <= 50 else 25
            if d >= need:
                add("park_ok_cars", "ok", "parking", n=cars, need=need, d=d)
            else:
                add("park_fail_cars", "error", "parking", n=cars, need=need, d=d, short=round(need - d, 2))
        elif d < 10:
            add("park_lt10", "error", "parking", d=d)
        elif d < 15:
            add("park_10_15", "warning", "parking", d=d)
        else:
            add("park_ok", "ok", "parking", d=d)

    if "fire_access" in active:
        w = p.driveway_width
        if not w:
            add("drive_missing", "warning", "fire_access")
        else:
            tall = p.floors > 4
            need = 4.2 if tall else 3.5
            code, level = ("drive_ok", "ok") if w >= need else ("drive_fail", "error")
            add(code, level, "fire_access", w=w, need=need, tall=tall)

    if not findings:
        add("nodata", "warning", "")

    levels = [f["level"] for f in findings]
    verdict = "fail" if "error" in levels else "clarify" if "warning" in levels else "ok"
    return {"verdict": verdict, "findings": findings}


# --- рендер замечаний на текущем языке ----------------------------------------------------
def finding_title(f: Dict) -> str:
    base = nf(NORMS_BY_ID[f["topic"]], "topic") if f["topic"] in NORMS_BY_ID else t("lvl_warning")
    return f"{base} — {t(f['sub'])}" if f["sub"] else base


def _format_args(args: Dict) -> Dict:
    out = {}
    for k, v in args.items():
        if isinstance(v, (tuple, list)) and v and v[0] == "dir":
            out[k] = t("dir_" + v[1])
        elif k == "tall":
            continue
        else:
            out[k] = fmt(v) if isinstance(v, float) else v
    if "tall" in args:
        out["note"] = t("tall_note") if args["tall"] else ""
    return out


def finding_text(f: Dict) -> str:
    return tf(FIND, f["code"], **_format_args(f["args"]))


def finding_rec(f: Dict) -> str:
    if f["level"] == "ok":
        return ""
    key = REC_MAP.get(f["code"], f["code"])
    if key not in REC:
        return ""
    return tf(REC, key, **_format_args(f["args"]))


def recommendations(findings: List[Dict]) -> List[str]:
    recs: List[str] = []
    for f in findings:
        r = finding_rec(f)
        if r and r not in recs:
            recs.append(r)
    recs.append(t("rec_final"))
    return recs


# =============================================================================
# 5. GEMINI (RAG-генерация)
# =============================================================================
def build_system_prompt(lang: str) -> str:
    idx = LANG_IDX[lang]
    heads = [S[k][idx] for k in ("verdict_lbl", "sec_refs", "sec_find", "sec_recs")]
    return f"""You are a senior architect-expert on the construction standards of the Republic of Kazakhstan (NormAI system).
Task: check the user's design decision against the RK norms supplied in the NORMATIVE CONTEXT.

RULES
1. Answer strictly in {LANG_NAMES[lang]}. Use a formal, precise, professional style. Do not use emojis.
2. Take normative requirements ONLY from the NORMATIVE CONTEXT. Never invent clause numbers, table numbers or figures
   that are not in the context. If the context is insufficient, say so openly and assess as clarification required.
3. If user data is missing, state exactly which data is needed.
4. Show calculations (difference, shortfall) where relevant.
5. The very first line of your answer must be a machine-readable tag, exactly one of:
   [[VERDICT:OK]]   [[VERDICT:FAIL]]   [[VERDICT:CLARIFY]]
6. After the tag, structure the answer in Markdown with exactly these four blocks:

## {heads[0]}
(one sentence naming the verdict: {S['v_ok'][idx]} / {S['v_fail'][idx]} / {S['v_clarify'][idx]}, plus 1-2 sentences of explanation)

## {heads[1]}
(documents and requirements used, with the document code)

## {heads[2]}
(deviations with their magnitude; risks)

## {heads[3]}
(concrete, actionable measures)

7. Finish with one short sentence noting that this is an AI-assisted analysis and not a formal expert review.
"""


def params_lines(p: Params) -> List[str]:
    lines = []
    for f in fields(Params):
        v = getattr(p, f.name)
        if not v:
            continue
        if f.name == "orientation":
            v = t("dir_" + v)
        elif isinstance(v, float):
            v = fmt(v)
        lines.append(f"{t(PARAM_LABEL_KEY[f.name])}: {v}")
    return lines


def build_prompt(query: str, p: Params, retrieved: List[Dict]) -> str:
    chunks = []
    for i, r in enumerate(retrieved, 1):
        n = NORMS_BY_ID[r["id"]]
        codes = "; ".join(nf(DOCS[d], "code") for d in n["docs"])
        chunks.append(f"[{i}] {codes} — {nf(n, 'clause')}\nTopic: {nf(n, 'topic')}\nRequirement: {nf(n, 'text')}")
    context = "\n\n".join(chunks) or "(no matching provision was found in the library; be cautious and request clarification)"
    plines = "\n".join(f"- {x}" for x in params_lines(p)) or "- (no additional parameters supplied)"
    return (
        f"NORMATIVE CONTEXT:\n{context}\n\nPROJECT PARAMETERS:\n{plines}\n\n"
        f"USER REQUEST:\n{query.strip() or '(no free-text description; assess the parameters only)'}"
    )


def call_gemini(api_key: str, query: str, p: Params, retrieved: List[Dict], lang: str) -> Dict:
    """Возвращает {'verdict', 'text', 'lang', 'model'}. Бросает исключение при сбое."""
    try:
        client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=60_000))
    except Exception:
        client = genai.Client(api_key=api_key)
    config = types.GenerateContentConfig(system_instruction=build_system_prompt(lang), temperature=0.2)
    prompt = build_prompt(query, p, retrieved)
    last_err: Optional[Exception] = None
    for attempt in range(2):
        try:
            resp = client.models.generate_content(model=MODEL_NAME, contents=prompt, config=config)
            raw = (resp.text or "").strip()
            if not raw:
                raise RuntimeError("empty response")
            m = re.search(r"\[\[\s*VERDICT\s*:\s*(OK|FAIL|CLARIFY)\s*\]\]", raw, re.IGNORECASE)
            verdict = {"OK": "ok", "FAIL": "fail", "CLARIFY": "clarify"}[m.group(1).upper()] if m else "clarify"
            text = re.sub(r"\[\[\s*VERDICT\s*:[^\]]*\]\]", "", raw).strip()
            return {"verdict": verdict, "text": text, "lang": lang, "model": MODEL_NAME}
        except Exception as exc:  # сеть, квота, ключ
            last_err = exc
            time.sleep(1.2)
    raise last_err or RuntimeError("unknown error")


# =============================================================================
# 6. ОТЧЁТЫ (TXT / PDF) и ИСТОРИЯ
# =============================================================================
def strip_md(text: str) -> List[Tuple[str, str]]:
    """Markdown ответа модели -> блоки (kind, text) для TXT/PDF."""
    blocks = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        s = s.replace("**", "").replace("`", "").replace("__", "")
        if s.startswith("#"):
            blocks.append(("h3", s.lstrip("#").strip()))
        elif s.startswith(("- ", "* ", "• ")):
            blocks.append(("li", s[2:].strip()))
        else:
            blocks.append(("p", s))
    return blocks


def record_primary_verdict(rec: Dict) -> str:
    return rec["api"]["verdict"] if rec.get("api") else rec["local"]["verdict"]


def record_findings_sorted(rec: Dict) -> List[Dict]:
    order = {"error": 0, "warning": 1, "ok": 2}
    return sorted(rec["local"]["findings"], key=lambda f: order[f["level"]])


def refs_for_record(rec: Dict) -> List[str]:
    out = []
    for nid in rec["active_ids"]:
        n = NORMS_BY_ID[nid]
        codes = ", ".join(nf(DOCS[d], "code") for d in n["docs"])
        out.append(f"{codes} — {nf(n, 'clause')}")
    return out


def params_lines_from_dict(d: Dict) -> List[str]:
    p = Params(**{k: v for k, v in d.items() if k in {f.name for f in fields(Params)}})
    return params_lines(p)


def report_blocks(rec: Dict) -> List[Tuple[str, str]]:
    b: List[Tuple[str, str]] = []
    mode = t("m_ai") if rec.get("api") else t("m_demo")
    b.append(("title", t("rp_title")))
    b.append(("meta", f"{APP_NAME} v{APP_VERSION} | ArchiCore | {rec['ts']} (UTC+5)"))
    b.append(("meta", f"{t('rp_mode')}: {mode} | {t('rp_lang')}: {rec['lang'].upper()}"))
    b.append(("h2", t("sec_query")))
    b.append(("p", rec["query"].strip() or "—"))
    plines = params_lines_from_dict(rec["params"])
    if plines:
        b.append(("h2", t("used_params")))
        b += [("li", x) for x in plines]
    b.append(("h2", t("verdict_lbl")))
    b.append(("verdict:" + record_primary_verdict(rec), t("v_" + record_primary_verdict(rec))))
    if rec.get("api"):
        b.append(("h2", t("ai_block")))
        b += strip_md(rec["api"]["text"])
        b.append(("h2", t("rule_block") + f" — {t('v_' + rec['local']['verdict'])}"))
    b.append(("h2", t("sec_refs")))
    b += [("li", x) for x in refs_for_record(rec)] or [("p", "—")]
    b.append(("h2", t("sec_find")))
    for f in record_findings_sorted(rec):
        b.append(("li", f"[{t('lvl_' + f['level'])}] {finding_title(f)}: {finding_text(f)}"))
    b.append(("h2", t("sec_recs")))
    b += [("li", x) for x in recommendations(rec["local"]["findings"])]
    b.append(("note", t("rp_disc")))
    return b


def build_txt(records: List[Dict]) -> str:
    out: List[str] = []
    for i, rec in enumerate(records):
        if i:
            out += ["", "=" * 78, ""]
        for kind, text in report_blocks(rec):
            if kind == "title":
                out += [text.upper(), "-" * min(len(text), 78)]
            elif kind == "meta":
                out.append(text)
            elif kind == "h2":
                out += ["", f"[ {text} ]"]
            elif kind == "h3":
                out.append(f"  {text}")
            elif kind == "li":
                out.append(f"  - {text}")
            elif kind.startswith("verdict:"):
                out.append(f"  >> {text.upper()}")
            elif kind == "note":
                out += ["", text]
            else:
                out.append(text)
    return "\n".join(out) + "\n"


def find_fonts() -> Optional[Tuple[str, str]]:
    """Ищет Unicode-шрифт (DejaVu Sans) с поддержкой кириллицы и казахских букв."""
    dirs = [
        "/usr/share/fonts/truetype/dejavu",
        "/usr/share/fonts/dejavu",
        "/usr/share/fonts/TTF",
        "/Library/Fonts",
        "C:\\Windows\\Fonts",
    ]
    try:
        import matplotlib

        dirs.append(os.path.join(matplotlib.get_data_path(), "fonts", "ttf"))
    except Exception:
        pass
    for d in dirs:
        reg = os.path.join(d, "DejaVuSans.ttf")
        if os.path.isfile(reg):
            bold = os.path.join(d, "DejaVuSans-Bold.ttf")
            return reg, bold if os.path.isfile(bold) else reg
    return None


PDF_COLORS = {"ok": (63, 107, 79), "fail": (143, 47, 47), "clarify": (154, 107, 23)}


def _build_pdf(records: List[Dict]) -> Optional[bytes]:
    fonts = find_fonts()
    if not fonts:
        return None
    try:
        from fpdf import FPDF
    except Exception:
        return None

    class NormPDF(FPDF):
        def footer(self):
            self.set_y(-12)
            self.set_font("DV", "", 8)
            self.set_text_color(120, 112, 100)
            self.cell(0, 5, f"{APP_NAME} · ArchiCore · {self.page_no()}", align="C")

    pdf = NormPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(18, 16, 18)
    pdf.add_font("DV", "", fonts[0])
    pdf.add_font("DV", "B", fonts[1])
    ink = (28, 26, 23)

    def para(text, size=10, style="", color=ink, h=5.4, indent=0.0):
        pdf.set_font("DV", style, size)
        pdf.set_text_color(*color)
        pdf.set_x(pdf.l_margin + indent)
        pdf.multi_cell(0, h, text, new_x="LMARGIN", new_y="NEXT")

    for rec in records:
        pdf.add_page()
        pdf.set_fill_color(27, 25, 22)
        pdf.rect(0, 0, 210, 6, "F")
        pdf.ln(4)
        for kind, text in report_blocks(rec):
            if kind == "title":
                para(text, 17, "B", h=8)
                pdf.ln(1)
            elif kind == "meta":
                para(text, 8.5, "", (110, 101, 90), h=4.6)
            elif kind == "h2":
                pdf.ln(3)
                para(text.upper(), 9.5, "B", (156, 122, 75), h=5.5)
                y = pdf.get_y()
                pdf.set_draw_color(214, 204, 186)
                pdf.line(pdf.l_margin, y, 210 - pdf.r_margin, y)
                pdf.ln(1.5)
            elif kind == "h3":
                para(text, 10, "B", h=5.6)
            elif kind == "li":
                para("•  " + text, 10, "", h=5.4, indent=3)
            elif kind.startswith("verdict:"):
                para(text, 13, "B", PDF_COLORS[kind.split(":")[1]], h=7)
            elif kind == "note":
                pdf.ln(4)
                para(text, 8.5, "", (110, 101, 90), h=4.6)
            else:
                para(text)
    return bytes(pdf.output())


@st.cache_data(show_spinner=False, max_entries=32)
def pdf_bytes(records_json: str, lang: str) -> Optional[bytes]:
    """PDF кэшируется по (JSON записей, язык). Язык нужен, т.к. t() читает его из session_state."""
    try:
        return _build_pdf(json.loads(records_json))
    except Exception:
        return None


def get_pdf(records: List[Dict]) -> Optional[bytes]:
    return pdf_bytes(json.dumps(records, ensure_ascii=False, sort_keys=True), L())


def history() -> List[Dict]:
    return st.session_state.setdefault("history", [])


def valid_record(r) -> bool:
    try:
        return (
            isinstance(r, dict)
            and {"id", "ts", "lang", "query", "params", "active_ids", "local"} <= set(r)
            and all(i in NORMS_BY_ID for i in r["active_ids"])
            and r["local"]["verdict"] in ("ok", "fail", "clarify")
            and all(f["code"] in FIND for f in r["local"]["findings"])
            and (r.get("api") is None or r["api"]["verdict"] in ("ok", "fail", "clarify"))
        )
    except Exception:
        return False


# =============================================================================
# 7. UI: СТИЛИ И КОМПОНЕНТЫ
# =============================================================================
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Serif:wght@500;600&display=swap');
:root{--bg:#f1ece2;--card:#fbf8f2;--ink:#1c1a17;--mute:#6b6357;--line:#ddd3c0;--dark:#1b1916;
--bronze:#9c7a4b;--ok:#3f6b4f;--fail:#8f2f2f;--warn:#9a6b17;
--shadow:0 1px 2px rgba(28,26,23,.06),0 10px 28px rgba(28,26,23,.07);}
html,body,.stApp{font-family:'IBM Plex Sans','Segoe UI',system-ui,sans-serif;}
.stApp{background:var(--bg);color:var(--ink);}
[data-testid="stMain"] .block-container{padding-top:2.2rem;max-width:1180px;}
[data-testid="stMain"] p,[data-testid="stMain"] li,[data-testid="stMain"] label{color:var(--ink);}
[data-testid="stHeader"]{background:transparent;}
#MainMenu,footer{visibility:hidden;}
/* sidebar */
section[data-testid="stSidebar"]{background:var(--dark);border-right:1px solid #000;}
section[data-testid="stSidebar"] *{color:#e8e1d2;}
section[data-testid="stSidebar"] input{color:#1c1a17 !important;background:#f1ece2 !important;}
section[data-testid="stSidebar"] [data-baseweb="select"] *{color:#1c1a17 !important;}
section[data-testid="stSidebar"] hr{border-color:#3a362f;}
.nx-brand{font-family:'IBM Plex Serif',Georgia,serif;font-size:1.55rem;letter-spacing:.08em;margin:.2rem 0 0 0;color:#f1ece2;}
.nx-brand-sub{font-size:.68rem;letter-spacing:.22em;text-transform:uppercase;color:#a99a7e;margin-bottom:.4rem;}
.nx-small{font-size:.76rem;line-height:1.45;color:#a99a7e !important;}
/* page header */
.nx-kicker{font-size:.72rem;letter-spacing:.24em;text-transform:uppercase;color:var(--bronze);margin-bottom:.15rem;}
.nx-title{font-family:'IBM Plex Serif',Georgia,serif;font-size:2.15rem;font-weight:600;line-height:1.15;margin:0;color:var(--ink);}
.nx-sub{color:var(--mute);margin:.35rem 0 0 0;font-size:1rem;}
.nx-rule{height:1px;background:linear-gradient(90deg,var(--ink) 0,var(--ink) 64px,var(--line) 64px);margin:1rem 0 1.5rem 0;}
.nx-h{font-family:'IBM Plex Serif',Georgia,serif;font-size:1.18rem;font-weight:600;margin:1.6rem 0 .7rem 0;color:var(--ink);}
.nx-h small{font-family:'IBM Plex Sans',sans-serif;font-weight:400;font-size:.8rem;color:var(--mute);margin-left:.5rem;}
/* cards */
.nx-card{background:var(--card);border:1px solid var(--line);border-radius:6px;box-shadow:var(--shadow);padding:1.15rem 1.35rem;}
.nx-card p{margin:0 0 .5rem 0;line-height:1.6;}
.nx-card .nx-team{color:var(--mute);font-size:.86rem;margin:.6rem 0 0 0;}
.nx-kpi{background:var(--card);border:1px solid var(--line);border-top:3px solid var(--dark);border-radius:6px;box-shadow:var(--shadow);padding:.9rem 1.1rem;}
.nx-kpi-l{font-size:.72rem;letter-spacing:.14em;text-transform:uppercase;color:var(--mute);}
.nx-kpi-v{font-family:'IBM Plex Serif',Georgia,serif;font-size:2.1rem;line-height:1.15;margin:.15rem 0;color:var(--ink);}
.nx-kpi-s{font-size:.78rem;color:var(--mute);}
.nx-step{background:var(--card);border:1px solid var(--line);border-radius:6px;box-shadow:var(--shadow);padding:1rem 1.2rem;height:100%;}
.nx-step b{display:block;margin:.2rem 0 .25rem 0;}
.nx-step-n{font-family:'IBM Plex Serif',serif;color:var(--bronze);font-size:1.25rem;}
.nx-step span{color:var(--mute);font-size:.92rem;line-height:1.5;}
/* verdict */
.nx-verdict{display:flex;align-items:center;gap:1.1rem;background:var(--card);border:1px solid var(--line);border-left:6px solid var(--mute);
border-radius:6px;box-shadow:var(--shadow);padding:1rem 1.3rem;margin:.4rem 0 1rem 0;}
.nx-verdict.ok{border-left-color:var(--ok);} .nx-verdict.fail{border-left-color:var(--fail);} .nx-verdict.clarify{border-left-color:var(--warn);}
.nx-verdict .l{font-size:.7rem;letter-spacing:.2em;text-transform:uppercase;color:var(--mute);}
.nx-verdict .v{font-family:'IBM Plex Serif',serif;font-size:1.55rem;font-weight:600;}
.nx-verdict.ok .v{color:var(--ok);} .nx-verdict.fail .v{color:var(--fail);} .nx-verdict.clarify .v{color:var(--warn);}
.nx-verdict .s{margin-left:auto;font-size:.78rem;color:var(--mute);text-align:right;}
/* findings */
.nx-find{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--mute);border-radius:6px;box-shadow:var(--shadow);
padding:.8rem 1.1rem;margin:0 0 .6rem 0;}
.nx-find.error{border-left-color:var(--fail);} .nx-find.warning{border-left-color:var(--warn);} .nx-find.ok{border-left-color:var(--ok);}
.nx-find-h{font-weight:600;margin-bottom:.15rem;}
.nx-find .nx-tag{color:#fff !important;}
.nx-tag{display:inline-block;font-size:.66rem;letter-spacing:.12em;text-transform:uppercase;padding:.08rem .45rem;border-radius:3px;margin-right:.5rem;color:#fff;vertical-align:middle;}
.nx-find.error .nx-tag{background:var(--fail);} .nx-find.warning .nx-tag{background:var(--warn);} .nx-find.ok .nx-tag{background:var(--ok);}
.nx-find-b{color:#3a352e;line-height:1.55;font-size:.95rem;}
.nx-ref{font-size:.93rem;line-height:1.5;padding:.35rem 0;border-bottom:1px solid var(--line);} .nx-ref:last-child{border-bottom:none;}
.nx-ref b{font-weight:600;}
.nx-chip{display:inline-block;font-size:.7rem;letter-spacing:.08em;text-transform:uppercase;padding:.1rem .5rem;border-radius:3px;border:1px solid var(--line);color:var(--mute);margin-right:.35rem;}
.nx-chip.ok{background:#e4eee7;color:var(--ok);border-color:#c5d8cb;} .nx-chip.fail{background:#f1dfdf;color:var(--fail);border-color:#e1bcbc;}
.nx-chip.clarify{background:#f3e8d1;color:var(--warn);border-color:#e2cfa5;}
.nx-fig{font-family:'IBM Plex Serif',serif;font-size:1.4rem;color:var(--ink);}
/* bars */
.nx-bar-row{display:flex;align-items:center;gap:.7rem;margin:.45rem 0;font-size:.88rem;}
.nx-bar-l{width:42%;color:var(--ink);} .nx-bar-t{flex:1;background:#e8e0cf;height:9px;border-radius:2px;overflow:hidden;}
.nx-bar-f{height:100%;background:var(--dark);} .nx-bar-f.ok{background:var(--ok);} .nx-bar-f.fail{background:var(--fail);} .nx-bar-f.clarify{background:var(--warn);}
.nx-bar-n{width:2rem;text-align:right;color:var(--mute);}
table.nx-t{width:100%;border-collapse:collapse;font-size:.88rem;} table.nx-t th{text-align:left;font-size:.68rem;letter-spacing:.14em;text-transform:uppercase;color:var(--mute);
border-bottom:1px solid var(--ink);padding:.35rem .4rem;} table.nx-t td{padding:.45rem .4rem;border-bottom:1px solid var(--line);vertical-align:top;}
/* widgets */
[data-testid="stMain"] input,[data-testid="stMain"] textarea{color:var(--ink) !important;}
[data-testid="stMain"] textarea,[data-testid="stMain"] [data-baseweb="input"],[data-testid="stMain"] [data-baseweb="select"]>div{background:#fffdf8 !important;border-color:#d5cab6 !important;}
[data-testid="stMain"] [data-baseweb="select"] *{color:var(--ink);}
[data-testid="stBaseButton-secondary"],[data-testid="stBaseButton-primary"],button[kind="secondary"],button[kind="primary"]{border-radius:3px;font-weight:500;letter-spacing:.02em;}
[data-testid="stBaseButton-primary"],button[kind="primary"]{background:var(--dark);color:#f1ece2 !important;border:1px solid var(--dark);}
[data-testid="stBaseButton-primary"]:hover,button[kind="primary"]:hover{background:var(--bronze);border-color:var(--bronze);}
[data-testid="stBaseButton-primary"] p,button[kind="primary"] p{color:#f1ece2 !important;}
[data-testid="stBaseButton-secondary"],button[kind="secondary"]{background:var(--card);border:1px solid #bdb19a;color:var(--ink);}
[data-testid="stBaseButton-secondary"]:hover,button[kind="secondary"]:hover{border-color:var(--ink);color:var(--ink);}
[data-testid="stExpander"]{background:var(--card);border:1px solid var(--line) !important;border-radius:6px;}
button[data-baseweb="tab"]{font-weight:500;color:var(--mute);} button[data-baseweb="tab"][aria-selected="true"]{color:var(--ink);}
div[data-baseweb="tab-highlight"]{background-color:var(--dark) !important;}
</style>
"""


def esc(x) -> str:
    return html.escape(str(x))


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def page_header(kick_key: str, title_key: str, sub_key: str) -> None:
    st.markdown(
        f"<div class='nx-kicker'>{esc(t(kick_key))}</div><h1 class='nx-title'>{esc(t(title_key))}</h1>"
        f"<p class='nx-sub'>{esc(t(sub_key))}</p><div class='nx-rule'></div>",
        unsafe_allow_html=True,
    )


def section(title: str, small: str = "") -> None:
    extra = f"<small>{esc(small)}</small>" if small else ""
    st.markdown(f"<div class='nx-h'>{esc(title)}{extra}</div>", unsafe_allow_html=True)


def kpi(label: str, value, sub: str = "") -> str:
    return (f"<div class='nx-kpi'><div class='nx-kpi-l'>{esc(label)}</div>"
            f"<div class='nx-kpi-v'>{esc(value)}</div><div class='nx-kpi-s'>{esc(sub)}</div></div>")


def bars(rows: List[Tuple[str, int, str]]) -> str:
    top = max([r[1] for r in rows] + [1])
    out = ""
    for label, n, cls in rows:
        w = int(100 * n / top)
        out += (f"<div class='nx-bar-row'><div class='nx-bar-l'>{esc(label)}</div>"
                f"<div class='nx-bar-t'><div class='nx-bar-f {cls}' style='width:{w}%'></div></div>"
                f"<div class='nx-bar-n'>{n}</div></div>")
    return out


def verdict_banner(verdict: str, source: str) -> None:
    st.markdown(
        f"<div class='nx-verdict {verdict}'><div><div class='l'>{esc(t('verdict_lbl'))}</div>"
        f"<div class='v'>{esc(t('v_' + verdict))}</div></div><div class='s'>{esc(source)}</div></div>",
        unsafe_allow_html=True,
    )


def keepalive(keys: List[str]) -> None:
    """Сохраняет состояние виджетов при переходе между страницами st.navigation."""
    for k in keys:
        if k in st.session_state:
            st.session_state[k] = st.session_state[k]


# =============================================================================
# 8. СТРАНИЦЫ
# =============================================================================
INPUT_KEYS = ["query_text", "in_floors", "in_distance", "in_orient", "in_own", "in_nb", "in_hours",
              "in_corr", "in_door", "in_height", "in_park", "in_cars", "in_drive"]


INPUT_DEFAULTS = {"query_text": "", "in_floors": 0, "in_distance": 0.0, "in_orient": "", "in_own": "", "in_nb": "",
                  "in_hours": 0.0, "in_corr": 0.0, "in_door": 0.0, "in_height": 0.0, "in_park": 0.0,
                  "in_cars": 0, "in_drive": 0.0}


def get_secret_key() -> str:
    try:
        return st.secrets.get("GEMINI_API_KEY", "") or ""
    except Exception:
        return ""


def render_sidebar() -> None:
    with st.sidebar:
        st.markdown(f"<div class='nx-brand'>{APP_NAME}</div>"
                    f"<div class='nx-brand-sub'>RAG · ҚР / RK / КЗ</div>", unsafe_allow_html=True)
        st.selectbox(t("lang_label"), LANGS, key="lang", format_func=lambda c: LANG_LABELS[c])
        st.radio(t("mode_label"), ["api", "demo"], key="mode",
                 format_func=lambda m: t("mode_api") if m == "api" else t("mode_demo"))
        if st.session_state.get("mode") == "api":
            st.text_input(t("api_key"), type="password", key="api_key", placeholder="AIza...",
                          help=t("api_key_help"))
            if get_secret_key() and not st.session_state.get("api_key"):
                st.markdown(f"<div class='nx-small'>{esc(t('server_key'))}</div>", unsafe_allow_html=True)
            elif not st.session_state.get("api_key"):
                st.markdown(f"<div class='nx-small'>{esc(t('no_key_note'))}</div>", unsafe_allow_html=True)
        else:
            st.markdown(f"<div class='nx-small'>{esc(t('demo_note'))}</div>", unsafe_allow_html=True)
        st.divider()
        st.markdown(f"<div class='nx-small'>{esc(t('team'))}</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='nx-small' style='margin-top:.6rem'>{esc(t('sb_foot'))}</div>"
                    f"<div class='nx-small' style='margin-top:.6rem'>v{APP_VERSION}</div>", unsafe_allow_html=True)


# --- главная --------------------------------------------------------------------------------------
def page_dashboard() -> None:
    page_header("kick_dashboard", "dash_title", "dash_sub")
    hist = history()
    verdicts = [record_primary_verdict(r) for r in hist]

    st.markdown(
        f"<div class='nx-card'><p>{esc(t('about_text'))}</p><p class='nx-team'>{esc(t('team'))}</p></div>",
        unsafe_allow_html=True,
    )
    section(t("kpi_checks"), t("kpi_session"))
    c = st.columns(4)
    c[0].markdown(kpi(t("kpi_checks"), len(hist), t("kpi_session")), unsafe_allow_html=True)
    c[1].markdown(kpi(t("kpi_fail"), verdicts.count("fail"), t("kpi_session")), unsafe_allow_html=True)
    c[2].markdown(kpi(t("kpi_clarify"), verdicts.count("clarify"), t("kpi_session")), unsafe_allow_html=True)
    c[3].markdown(kpi(t("kpi_norms"), len(NORMS), t("kpi_docs", n=len(DOCS))), unsafe_allow_html=True)

    section(t("quick_title"), t("quick_sub"))
    qc = st.columns(3)
    for col, k in zip(qc, ["fire", "ins", "evac"]):
        with col:
            if st.button(t("ex_" + k), key=f"qs_{k}"):
                st.session_state["query_text"] = t(f"ex_{k}_text")
                st.switch_page(PAGES["inspector"])

    left, right = st.columns(2)
    with left:
        section(t("verdict_dist"))
        if hist:
            rows = [(t("v_ok"), verdicts.count("ok"), "ok"), (t("v_fail"), verdicts.count("fail"), "fail"),
                    (t("v_clarify"), verdicts.count("clarify"), "clarify")]
            st.markdown(f"<div class='nx-card'>{bars(rows)}</div>", unsafe_allow_html=True)
        else:
            st.markdown(f"<div class='nx-card'>{esc(t('no_data'))}</div>", unsafe_allow_html=True)
    with right:
        section(t("topic_freq"))
        if hist:
            counts: Dict[str, int] = {}
            for r in hist:
                for nid in r["active_ids"]:
                    counts[nid] = counts.get(nid, 0) + 1
            rows = [(nf(NORMS_BY_ID[k], "topic"), v, "") for k, v in sorted(counts.items(), key=lambda kv: -kv[1])[:5]]
            st.markdown(f"<div class='nx-card'>{bars(rows)}</div>", unsafe_allow_html=True)
        else:
            st.markdown(f"<div class='nx-card'>{esc(t('no_data'))}</div>", unsafe_allow_html=True)

    section(t("how_title"))
    hc = st.columns(3)
    for col, n in zip(hc, ["1", "2", "3"]):
        col.markdown(
            f"<div class='nx-step'><span class='nx-step-n'>0{n}</span><b>{esc(t(f'how{n}_t'))}</b>"
            f"<span>{esc(t(f'how{n}_d'))}</span></div>", unsafe_allow_html=True)

    section(t("coverage"))
    st.markdown("<div class='nx-card'>" + "".join(
        f"<div class='nx-ref'><b>{esc(nf(n, 'topic'))}</b> &nbsp;·&nbsp; "
        f"{esc(', '.join(nf(DOCS[d], 'code') for d in n['docs']))}</div>" for n in NORMS) + "</div>",
        unsafe_allow_html=True)

    if hist:
        section(t("recent"))
        rows_html = "".join(
            f"<tr><td>{esc(r['ts'])}</td><td><span class='nx-chip {record_primary_verdict(r)}'>"
            f"{esc(t('v_' + record_primary_verdict(r)))}</span></td><td>{esc(short(r['query'], 110))}</td></tr>"
            for r in reversed(hist[-5:]))
        st.markdown(f"<div class='nx-card'><table class='nx-t'><tr><th>{esc(t('col_time'))}</th>"
                    f"<th>{esc(t('col_verdict'))}</th><th>{esc(t('col_query'))}</th></tr>{rows_html}</table></div>",
                    unsafe_allow_html=True)


def short(s: str, n: int) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


# --- инспектор -----------------------------------------------------------------------------------------
def set_example(text: str) -> None:
    st.session_state["query_text"] = text


def read_form() -> Params:
    ss = st.session_state
    return Params(
        floors=int(ss.get("in_floors", 0) or 0),
        neighbor_distance=float(ss.get("in_distance", 0.0) or 0.0),
        orientation=ss.get("in_orient", "") or "",
        own_degree=ss.get("in_own", "") or "",
        neighbor_degree=ss.get("in_nb", "") or "",
        corridor_width=float(ss.get("in_corr", 0.0) or 0.0),
        door_width=float(ss.get("in_door", 0.0) or 0.0),
        floor_height=float(ss.get("in_height", 0.0) or 0.0),
        parking_distance=float(ss.get("in_park", 0.0) or 0.0),
        parking_cars=int(ss.get("in_cars", 0) or 0),
        insolation_hours=float(ss.get("in_hours", 0.0) or 0.0),
        driveway_width=float(ss.get("in_drive", 0.0) or 0.0),
    )


def run_check(query: str, form: Params) -> Tuple[Dict, List[Tuple[str, str]]]:
    """Полный пайплайн: параметры -> retrieve -> (Gemini | правила) -> запись истории."""
    lang = L()
    params = merge_params(form, extract_from_text(query))
    implied = implied_topics(params)
    retrieved = retrieve_norms(query, hints=implied)
    active = [r["id"] for r in retrieved] + [i for i in NORMS_BY_ID if i in implied and i not in [r["id"] for r in retrieved]]
    local = analyze(params, set(active))

    notices: List[Tuple[str, str]] = []
    api_result = None
    user_key = (st.session_state.get("api_key") or "").strip()
    server_key = get_secret_key()
    key = user_key or server_key
    if st.session_state.get("mode") == "api":
        if not key:
            notices.append(("info", t("n_nokey")))
        elif not GENAI_AVAILABLE:
            notices.append(("warning", t("n_nolib")))
        elif not user_key and st.session_state.get("server_calls", 0) >= MAX_SERVER_KEY_CALLS:
            notices.append(("warning", t("n_limit")))
        else:
            try:
                with st.spinner(t("spin")):
                    api_result = call_gemini(key, query, params, retrieved, lang)
                if not user_key:
                    st.session_state["server_calls"] = st.session_state.get("server_calls", 0) + 1
            except Exception as exc:
                notices.append(("error", t("n_fail", err=short(str(exc), 140))))

    record = {
        "id": uuid.uuid4().hex[:10],
        "ts": now_str(),
        "lang": lang,
        "query": query,
        "params": asdict(params),
        "retrieved": retrieved,
        "active_ids": active,
        "local": local,
        "api": api_result,
    }
    return record, notices


def render_findings_block(rec: Dict) -> None:
    section(t("sec_refs"))
    refs = refs_for_record(rec)
    st.markdown("<div class='nx-card'>" + ("".join(f"<div class='nx-ref'>{esc(r)}</div>" for r in refs) or "—") + "</div>",
                unsafe_allow_html=True)
    section(t("sec_find"))
    for f in record_findings_sorted(rec):
        st.markdown(
            f"<div class='nx-find {f['level']}'><div class='nx-find-h'><span class='nx-tag'>{esc(t('lvl_' + f['level']))}</span>"
            f"{esc(finding_title(f))}</div><div class='nx-find-b'>{esc(finding_text(f))}</div></div>",
            unsafe_allow_html=True)
    section(t("sec_recs"))
    st.markdown("<div class='nx-card'>" + "".join(
        f"<div class='nx-ref'>{i}. {esc(r)}</div>" for i, r in enumerate(recommendations(rec["local"]["findings"]), 1)) + "</div>",
        unsafe_allow_html=True)


def render_fragments(rec: Dict) -> None:
    with st.expander(f"{t('sec_frag')} ({len(rec['retrieved'])})"):
        if not rec["retrieved"]:
            st.write(t("no_frag"))
        for r in rec["retrieved"]:
            n = NORMS_BY_ID[r["id"]]
            codes = ", ".join(nf(DOCS[d], "code") for d in n["docs"])
            matched = ", ".join(r["matched"]) if r["matched"] else t("by_params")
            st.markdown(f"**{codes}** — {nf(n, 'clause')}")
            st.caption(f"{nf(n, 'topic')} · {t('score')}: {r['score']} · {t('matched')}: {matched}")
            st.write(nf(n, "text"))
            st.divider()


def render_downloads(rec_list: List[Dict], ctx: str, label_suffix: str = "") -> None:
    c1, c2, _ = st.columns([1, 1, 2])
    c1.download_button(t("dl_txt") + label_suffix, data=build_txt(rec_list), file_name=f"normai_{ctx}.txt",
                       mime="text/plain", key=f"dl_txt_{ctx}")
    pdf = get_pdf(rec_list)
    if pdf:
        c2.download_button(t("dl_pdf") + label_suffix, data=pdf, file_name=f"normai_{ctx}.pdf",
                           mime="application/pdf", key=f"dl_pdf_{ctx}")
    else:
        st.caption(t("pdf_na"))


def render_record(rec: Dict, ctx: str) -> None:
    verdict = record_primary_verdict(rec)
    source = t("src_ai") if rec.get("api") else t("src_rule")
    verdict_banner(verdict, f"{source} · {rec['ts']}")

    plines = params_lines_from_dict(rec["params"])
    if plines:
        with st.expander(t("used_params")):
            for x in plines:
                st.markdown(f"- {x}")

    if rec.get("api"):
        section(t("ai_block"), f"{rec['api']['model']} · {rec['api']['lang'].upper()}")
        with st.container(border=True):
            st.markdown(rec["api"]["text"])
            st.caption(t("ai_disc"))
        with st.expander(f"{t('rule_block')} — {t('v_' + rec['local']['verdict'])}"):
            render_findings_block(rec)
    else:
        render_findings_block(rec)
    render_fragments(rec)
    st.markdown("<div style='height:.6rem'></div>", unsafe_allow_html=True)
    render_downloads([rec], ctx)


def page_inspector() -> None:
    page_header("kick_inspector", "insp_title", "insp_sub")

    section(t("samples"))
    cols = st.columns(3)
    for col, k in zip(cols, ["fire", "ins", "evac"]):
        col.button(t("ex_" + k), key=f"ex_{k}", on_click=set_example, args=(t(f"ex_{k}_text"),))

    section(t("desc_label"))
    st.text_area(t("desc_label"), key="query_text", height=150, placeholder=t("desc_ph"),
                 label_visibility="collapsed")

    c1, c2, c3 = st.columns(3)
    c1.number_input(t("f_floors"), min_value=0, max_value=200, step=1, key="in_floors", help=t("zero_help"))
    c2.number_input(t("f_distance"), min_value=0.0, max_value=500.0, step=0.5, key="in_distance",
                    help=t("zero_help"))
    c3.selectbox(t("f_orient"), DIRECTIONS, key="in_orient",
                 format_func=lambda d: t("not_set") if not d else t("dir_" + d))

    with st.expander(t("extra")):
        e1, e2, e3 = st.columns(3)
        e1.selectbox(t("f_own"), DEGREES, key="in_own", format_func=lambda d: d or t("not_set"))
        e2.selectbox(t("f_nb"), DEGREES, key="in_nb", format_func=lambda d: d or t("not_set"))
        e3.number_input(t("f_hours"), min_value=0.0, max_value=24.0, step=0.1, key="in_hours")
        e4, e5, e6 = st.columns(3)
        e4.number_input(t("f_corr"), min_value=0.0, max_value=20.0, step=0.1, key="in_corr")
        e5.number_input(t("f_door"), min_value=0.0, max_value=10.0, step=0.05, key="in_door")
        e6.number_input(t("f_height"), min_value=0.0, max_value=10.0, step=0.05, key="in_height")
        e7, e8, e9 = st.columns(3)
        e7.number_input(t("f_park"), min_value=0.0, max_value=200.0, step=0.5, key="in_park")
        e8.number_input(t("f_cars"), min_value=0, max_value=1000, step=1, key="in_cars")
        e9.number_input(t("f_drive"), min_value=0.0, max_value=20.0, step=0.1, key="in_drive")

    if st.button(t("run"), type="primary", key="run_check"):
        query = st.session_state.get("query_text", "")
        form = read_form()
        merged = merge_params(form, extract_from_text(query))
        if not query.strip() and not has_any_param(merged):
            st.warning(t("empty_input"))
        else:
            record, notices = run_check(query, form)
            history().append(record)
            st.session_state["last_record_id"] = record["id"]
            st.session_state["last_notices"] = notices

    last = next((r for r in history() if r["id"] == st.session_state.get("last_record_id")), None)
    if last:
        st.markdown("<div class='nx-rule' style='margin-top:2rem'></div>", unsafe_allow_html=True)
        section(t("result_title"))
        for kind, msg in st.session_state.get("last_notices", []):
            getattr(st, kind)(msg)
        render_record(last, f"insp_{last['id']}")


# --- база нормативов -------------------------------------------------------------------------------------
def norm_card(n: Dict) -> str:
    codes = " · ".join(nf(DOCS[d], "code") for d in n["docs"])
    fig, unit = n["figure"]
    return (
        f"<div class='nx-card' style='margin-bottom:.9rem'>"
        f"<div style='display:flex;justify-content:space-between;gap:1rem;align-items:flex-start'>"
        f"<div><div class='nx-kicker'>{esc(codes)}</div>"
        f"<div style='font-family:IBM Plex Serif,serif;font-size:1.08rem;font-weight:600'>{esc(nf(n, 'topic'))}</div>"
        f"<div class='nx-small' style='color:#6b6357 !important;margin:.15rem 0 .5rem 0'>{esc(t('clause_lbl'))}: {esc(nf(n, 'clause'))}</div></div>"
        f"<div style='text-align:right;min-width:120px'><div class='nx-kpi-l'>{esc(t('figure_lbl'))}</div>"
        f"<div class='nx-fig'>{esc(fig.replace(',', '.') if L() == 'en' else fig)} {esc(t('unit_m') if unit == 'm' else ('сағ' if L() == 'kk' else 'ч' if L() == 'ru' else 'h'))}</div></div></div>"
        f"<p style='margin:0;line-height:1.6'>{esc(nf(n, 'text'))}</p></div>"
    )


def page_norms() -> None:
    page_header("kick_norms", "norms_title", "norms_sub")
    st.info(t("norms_note"))
    tab_docs, tab_prov, tab_test = st.tabs([t("tab_docs"), t("tab_prov"), t("tab_test")])

    with tab_docs:
        for did, d in DOCS.items():
            topics = [nf(n, "topic") for n in NORMS if did in n["docs"]]
            st.markdown(
                f"<div class='nx-card' style='margin-bottom:.9rem'><div class='nx-kicker'>{esc(nf(d, 'code'))}</div>"
                f"<div style='font-family:IBM Plex Serif,serif;font-size:1.08rem;font-weight:600'>{esc(nf(d, 'title'))}</div>"
                f"<p style='margin:.4rem 0 .2rem 0'><b>{esc(t('doc_scope'))}:</b> {esc(nf(d, 'scope'))}</p>"
                f"<p style='margin:0;color:#6b6357'>{esc(' · '.join(topics))}</p></div>", unsafe_allow_html=True)

    with tab_prov:
        f1, f2 = st.columns([2, 1])
        q = f1.text_input(t("search"), key="kb_search")
        opts = [""] + list(DOCS)
        sel = f2.selectbox(t("filter_doc"), opts, key="kb_doc", format_func=lambda d: t("all_docs") if not d else nf(DOCS[d], "code"))
        shown = [n for n in NORMS if (not sel or sel in n["docs"])
                 and (not q or q.lower() in (nf(n, "topic") + " " + nf(n, "text") + " " + nf(n, "clause")).lower()
                      or any(q.lower() in kw for kw in n["kw"]))]
        st.caption(t("found_n", n=len(shown)))
        if not shown:
            st.write(t("no_match"))
        for n in shown:
            st.markdown(norm_card(n), unsafe_allow_html=True)

    with tab_test:
        st.caption(t("test_hint"))
        tq = st.text_input(t("search"), key="kb_test")
        if tq.strip():
            res = retrieve_norms(tq)
            if not res:
                st.write(t("no_match"))
            for r in res:
                n = NORMS_BY_ID[r["id"]]
                st.markdown(norm_card(n), unsafe_allow_html=True)
                st.caption(f"{t('score')}: {r['score']} · {t('matched')}: {', '.join(r['matched']) or '—'}")


# --- история и отчёты ----------------------------------------------------------------------------------------
def page_history() -> None:
    page_header("kick_history", "hist_title", "hist_sub")
    st.caption(t("hist_note"))
    hist = history()

    if hist:
        rows = "".join(
            f"<tr><td>{esc(r['ts'])}</td><td>{esc(t('m_ai') if r.get('api') else t('m_demo'))}</td>"
            f"<td><span class='nx-chip {record_primary_verdict(r)}'>{esc(t('v_' + record_primary_verdict(r)))}</span></td>"
            f"<td>{esc(short(r['query'], 120))}</td></tr>" for r in reversed(hist))
        st.markdown(f"<div class='nx-card'><table class='nx-t'><tr><th>{esc(t('col_time'))}</th><th>{esc(t('col_mode'))}</th>"
                    f"<th>{esc(t('col_verdict'))}</th><th>{esc(t('col_query'))}</th></tr>{rows}</table></div>",
                    unsafe_allow_html=True)

        section(t("exp_all"))
        render_downloads(hist, "all")
        j1, _ = st.columns([1, 3])
        j1.download_button(t("json_dl"), data=json.dumps(hist, ensure_ascii=False, indent=2),
                           file_name="normai_history.json", mime="application/json", key="dl_json")

        section(t("pick"))
        ids = [r["id"] for r in reversed(hist)]
        by_id = {r["id"]: r for r in hist}
        pick = st.selectbox(t("pick"), ids, key="hist_pick", label_visibility="collapsed",
                            format_func=lambda i: f"{by_id[i]['ts']} · {t('v_' + record_primary_verdict(by_id[i]))} · {short(by_id[i]['query'], 70)}")
        rec = by_id[pick]
        render_record(rec, f"hist_{rec['id']}")
        if st.button(t("delete"), key="hist_del"):
            st.session_state["history"] = [r for r in hist if r["id"] != pick]
            st.rerun()
        ok = st.checkbox(t("confirm_clear"), key="hist_confirm")
        if st.button(t("clear"), key="hist_clear", disabled=not ok):
            st.session_state["history"] = []
            st.session_state["last_record_id"] = None
            st.rerun()
    else:
        st.info(t("hist_empty"))

    section(t("json_ul"))
    up = st.file_uploader(t("json_ul"), type=["json"], key="hist_upload", label_visibility="collapsed")
    if up is not None and st.button(t("imp_btn"), key="hist_import"):
        try:
            data = json.loads(up.getvalue().decode("utf-8"))
            existing = {r["id"] for r in history()}
            fresh = [r for r in data if valid_record(r) and r["id"] not in existing] if isinstance(data, list) else None
            if fresh is None:
                st.error(t("imp_bad"))
            else:
                history().extend(fresh)
                history().sort(key=lambda r: r["ts"])
                st.success(t("imp_ok", n=len(fresh)))
        except Exception:
            st.error(t("imp_bad"))


# =============================================================================
# 9. ТОЧКА ВХОДА
# =============================================================================
def main() -> None:
    st.set_page_config(page_title="NormAI — ҚР / РК / KZ", page_icon=None, layout="wide",
                       initial_sidebar_state="expanded")
    ss = st.session_state
    ss.setdefault("lang", "kk")
    ss.setdefault("mode", "api" if get_secret_key() else "demo")
    for k, v in INPUT_DEFAULTS.items():
        ss.setdefault(k, v)
    keepalive(INPUT_KEYS + ["kb_search", "kb_doc", "kb_test", "api_key", "mode"])
    inject_css()

    PAGES["dashboard"] = st.Page(page_dashboard, title=t("nav_dashboard"), icon=":material/space_dashboard:", default=True)
    PAGES["inspector"] = st.Page(page_inspector, title=t("nav_inspector"), icon=":material/fact_check:", url_path="inspector")
    PAGES["norms"] = st.Page(page_norms, title=t("nav_norms"), icon=":material/menu_book:", url_path="standards")
    PAGES["history"] = st.Page(page_history, title=t("nav_history"), icon=":material/history:", url_path="history")

    pg = st.navigation(list(PAGES.values()))
    render_sidebar()
    pg.run()


if __name__ == "__main__":
    main()
