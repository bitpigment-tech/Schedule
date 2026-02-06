import json
import os
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from urllib import parse as urlparse
from urllib import request as urlrequest

from flask import Flask, jsonify, render_template_string, request

SCHEDULE_PAGE_URL = "https://www.miet.ru/schedule/"
SCHEDULE_DATA_URL = "https://miet.ru/schedule/data"

DEFAULT_GROUP = os.getenv("MIET_GROUP", "").strip() or "ИТД-11М"
TIMEZONE_OFFSET = int(os.getenv("MIET_TZ_OFFSET", "3"))
CACHE_TTL_SECONDS = int(os.getenv("MIET_CACHE_TTL", "300"))
REQUEST_TIMEOUT = float(os.getenv("MIET_TIMEOUT", "10"))
WEEK_SHIFT = int(os.getenv("MIET_WEEK_SHIFT", "0"))
WEEK_OVERRIDE = os.getenv("MIET_WEEK_OVERRIDE", "").strip()
if not WEEK_OVERRIDE and DEFAULT_GROUP == "ИТД-11М":
    WEEK_OVERRIDE = "1 числитель"
WEEK_START_STR = os.getenv("MIET_WEEK_START", "2026-02-02").strip()


@dataclass
class CacheEntry:
    ts: float
    value: object


_cache: dict[str, CacheEntry] = {}

app = Flask(__name__)


INDEX_HTML = """<!doctype html>
<html lang="ru">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Расписание МИЭТ</title>
    <link rel="icon" href="data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'><rect width='64' height='64' rx='14' fill='%230ea5e9'/><rect x='12' y='18' width='40' height='34' rx='6' fill='white'/><rect x='12' y='14' width='40' height='10' rx='5' fill='%23fde047'/><circle cx='22' cy='14' r='4' fill='%230f172a'/><circle cx='42' cy='14' r='4' fill='%230f172a'/><rect x='20' y='30' width='8' height='8' rx='2' fill='%230ea5e9'/><rect x='36' y='30' width='8' height='8' rx='2' fill='%230ea5e9'/><rect x='20' y='42' width='8' height='8' rx='2' fill='%230ea5e9'/><rect x='36' y='42' width='8' height='8' rx='2' fill='%230ea5e9'/></svg>"/>
    <style>
      @import url("https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Montserrat:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;600&display=swap");
      :root {
        --bg: #f4f6fb;
        --bg-2: #e9eef9;
        --panel: #ffffff;
        --panel-2: #f6f7fb;
        --ink: #0f172a;
        --muted: #5b6472;
        --accent: #0ea5e9;
        --accent-2: #2563eb;
        --border: rgba(15, 23, 42, 0.12);
        --header: rgba(15, 23, 42, 0.06);
        --glow: 0 8px 20px rgba(37, 99, 235, 0.12);
        --surface: #ffffff;
        --error-bg: #fee4e2;
        --error-border: #fecdca;
        --error-ink: #b42318;
        --font-body: "Inter", "Segoe UI", sans-serif;
        --week-text: #ffffff;
      }
      [data-theme="dark-blue"] {
        --bg: #0b0f16;
        --bg-2: #0f172a;
        --panel: #121a2b;
        --panel-2: #0f1524;
        --ink: #e2e8f0;
        --muted: #94a3b8;
        --accent: #4f46e5;
        --accent-2: #38bdf8;
        --border: rgba(148, 163, 184, 0.22);
        --header: rgba(148, 163, 184, 0.12);
        --glow: 0 0 30px rgba(79, 70, 229, 0.2);
        --surface: #0b1220;
        --error-bg: rgba(127, 29, 29, 0.35);
        --error-border: rgba(239, 68, 68, 0.4);
        --error-ink: #fecaca;
      }
      [data-theme="pastel-contrast"] {
        --bg: #151515;
        --bg-2: #101010;
        --panel: #1e1e1e;
        --panel-2: #1a1a1a;
        --ink: #e5e7eb;
        --muted: #a1a1aa;
        --accent: #a78bfa;
        --accent-2: #f59e0b;
        --border: rgba(148, 163, 184, 0.16);
        --header: rgba(167, 139, 250, 0.12);
        --glow: 0 0 24px rgba(167, 139, 250, 0.18);
        --surface: #121212;
        --error-bg: rgba(153, 27, 27, 0.35);
        --error-border: rgba(248, 113, 113, 0.45);
        --error-ink: #fecaca;
      }
      [data-theme="oxocarbon"] {
        --bg: #0b0b0b;
        --bg-2: #0d0d0d;
        --panel: #121212;
        --panel-2: #0f0f0f;
        --ink: #e5e7eb;
        --muted: #9ca3af;
        --accent: #fbbf24;
        --accent-2: #fde047;
        --border: rgba(250, 204, 21, 0.18);
        --header: rgba(250, 204, 21, 0.12);
        --glow: 0 0 22px rgba(250, 204, 21, 0.2);
        --surface: #111111;
        --error-bg: rgba(153, 27, 27, 0.35);
        --error-border: rgba(248, 113, 113, 0.45);
        --error-ink: #fecaca;
      }
      * { box-sizing: border-box; }
      html, body {
        background: linear-gradient(180deg, var(--bg) 0%, var(--bg-2) 100%);
      }
      body {
        margin: 0;
        font-family: var(--font-body);
        color: var(--ink);
        min-height: 100vh;
      }
      main {
        max-width: 1800px;
        width: 100%;
        margin: 0 auto;
        padding: 24px 16px 40px;
      }
      header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 6px;
        gap: 12px;
      }
      h1 {
        font-size: 28px;
        margin: 0;
        font-weight: 700;
        letter-spacing: 0.5px;
        line-height: 1.2;
      }
      .group-badge {
        display: inline-flex;
        align-items: center;
        gap: 10px;
        padding: 10px 16px;
        border-radius: 12px;
        background: var(--surface);
        color: var(--ink);
        font-weight: 700;
        letter-spacing: 1px;
        text-transform: uppercase;
        border: 1px solid var(--border);
        box-shadow: 0 8px 18px rgba(15, 23, 42, 0.18);
      }
      .theme-toggle {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 6px 10px;
        border-radius: 999px;
        border: 1px solid var(--border);
        background: var(--surface);
        color: var(--muted);
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: 0.8px;
      }
      .theme-toggle button {
        padding: 6px 10px;
        border-radius: 999px;
        border: 1px solid transparent;
        background: transparent;
        color: inherit;
        cursor: pointer;
        font-weight: 600;
        font-size: 12px;
      }
      .theme-toggle button.active {
        background: var(--accent);
        color: #ffffff;
        border-color: rgba(255, 255, 255, 0.2);
      }
      .font-toggle {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 6px 10px;
        border-radius: 999px;
        border: 1px solid var(--border);
        background: var(--surface);
        color: var(--muted);
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: 0.8px;
      }
      .font-toggle button {
        padding: 6px 10px;
        border-radius: 999px;
        border: 1px solid transparent;
        background: transparent;
        color: inherit;
        cursor: pointer;
        font-weight: 600;
        font-size: 12px;
      }
      .font-toggle button.active {
        background: var(--accent);
        color: #ffffff;
        border-color: rgba(255, 255, 255, 0.2);
      }
      button {
        padding: 9px 14px;
        border: 1px solid var(--accent);
        background: var(--accent);
        color: #fff;
        border-radius: 8px;
        cursor: pointer;
        font-weight: 600;
      }
      button.secondary {
        background: transparent;
        color: var(--accent);
      }
      .week-label {
        color: var(--muted);
        font-size: 14px;
        margin: 10px 0 20px;
      }
      .week-nav {
        display: flex;
        align-items: center;
        gap: 10px;
        margin: 18px 0 18px;
      }
      .week-nav button {
        padding: 6px 10px;
        font-size: 13px;
      }
      .week-current {
        font-size: 14px;
        color: var(--muted);
      }
      .week-card {
        display: inline-flex;
        align-items: center;
        gap: 10px;
        padding: 8px 12px;
        border-radius: 10px;
        background: #0f7690;
        color: #ffffff;
        font-weight: 600;
        font-size: 14px;
      }
      .week-card .lines {
        display: flex;
        flex-direction: column;
        line-height: 1.1;
      }
      .grid {
        display: grid;
        grid-template-columns: 1fr;
        gap: 24px;
      }
      @media (min-width: 900px) {
        .grid { grid-template-columns: 1fr 1fr; }
      }
      section {
        background: linear-gradient(160deg, var(--panel), var(--panel-2));
        border: 1px solid var(--border);
        border-radius: 16px;
        padding: 18px;
        min-height: 220px;
        box-shadow: var(--glow);
        backdrop-filter: blur(6px);
        animation: rise 320ms ease-out;
      }
      h2 {
        margin: 0 0 10px;
        font-size: 18px;
        color: var(--accent-2);
      }
      h3 {
        margin: 16px 0 8px;
        font-size: 15px;
        color: var(--accent-2);
        letter-spacing: 0.2px;
      }
      table {
        width: 100%;
        border-collapse: collapse;
        font-size: 14px;
        color: var(--ink);
      }
      th, td {
        padding: 8px 10px;
        border-bottom: 1px solid rgba(148, 163, 184, 0.18);
        text-align: left;
        vertical-align: top;
        white-space: pre-line;
      }
      table {
        table-layout: fixed;
      }
      th.col-lesson, td.col-lesson { width: 6%; }
      th.col-time, td.col-time { width: 12%; }
      th.col-subject, td.col-subject { width: 36%; }
      th.col-type, td.col-type { width: 8%; }
      th.col-teacher, td.col-teacher { width: 24%; }
      th.col-room, td.col-room { width: 14%; }
      th {
        background: var(--header);
        font-weight: 600;
        color: var(--ink);
        position: sticky;
        top: 0;
      }
      th.col-time {
        font-weight: 700;
      }
      .table-wrap {
        overflow-x: auto;
      }
      .empty {
        color: var(--muted);
        font-size: 14px;
        margin-top: 4px;
      }
      .error {
        color: var(--error-ink);
        background: var(--error-bg);
        border: 1px solid var(--error-border);
        padding: 10px 12px;
        border-radius: 8px;
        font-size: 14px;
      }
      .week-card {
        display: inline-flex;
        align-items: center;
        gap: 10px;
        padding: 10px 14px;
        border-radius: 12px;
        background: linear-gradient(135deg, var(--accent), var(--accent-2));
        border: 1px solid rgba(255, 255, 255, 0.28);
        color: var(--week-text);
        font-weight: 600;
        font-size: 14px;
        box-shadow: 0 6px 24px rgba(15, 23, 42, 0.45);
      }
      .week-card .lines {
        display: flex;
        flex-direction: column;
        line-height: 1.1;
      }
      .col-lesson {
        font-family: "IBM Plex Mono", "Consolas", monospace;
        font-variant-numeric: tabular-nums;
      }
      .col-time {
        font-family: inherit;
        font-variant-numeric: tabular-nums;
        font-weight: 400;
      }
      @keyframes rise {
        from { transform: translateY(6px); opacity: 0.6; }
        to { transform: translateY(0); opacity: 1; }
      }
      @media (max-width: 900px) {
        main {
          padding: 16px 16px 28px;
        }
        header {
          flex-direction: column;
          align-items: flex-start;
        }
        .group-badge {
          font-size: 16px;
          padding: 8px 12px;
        }
        .week-nav {
          flex-wrap: wrap;
          justify-content: flex-start;
          gap: 8px;
          margin: 14px 0 16px;
        }
        .font-toggle {
          width: auto;
          justify-content: flex-start;
        }
        .grid {
          gap: 16px;
        }
        section {
          padding: 14px;
        }
        table {
          table-layout: auto;
          font-size: 12px;
        }
        th, td {
          padding: 6px 8px;
        }
        th.col-lesson, td.col-lesson { width: 8%; }
        th.col-time, td.col-time { width: 16%; }
        th.col-subject, td.col-subject { width: 40%; }
        th.col-type, td.col-type { width: 8%; }
        th.col-teacher, td.col-teacher { width: 20%; }
        th.col-room, td.col-room { width: 8%; }
      }
    </style>
  </head>
  <body>
    <main>
      <header>
        <div class="group-badge" id="group-label">
          <span>{{ group or "—" }}</span>
        </div>
        <div style="display:flex; gap:10px; flex-wrap:wrap; justify-content:flex-end;">
          <div class="theme-toggle" id="theme-toggle">
            <button type="button" data-theme="light">Light</button>
            <button type="button" data-theme="dark-blue">Dark Blue</button>
            <button type="button" data-theme="pastel-contrast">Pastel Contrast</button>
            <button type="button" data-theme="oxocarbon">Oxocarbon</button>
          </div>
          <div class="font-toggle" id="font-toggle">
            <button type="button" data-font="inter">Inter</button>
            <button type="button" data-font="montserrat">Montserrat</button>
          </div>
        </div>
      </header>
      <div class="week-nav">
        <button type="button" id="prev-week">◀</button>
        <div class="week-current" id="week-label"></div>
        <button type="button" id="next-week">▶</button>
      </div>
      <div class="grid">
        <section>
          <h2>Сегодня</h2>
          <h3 id="today-label"></h3>
          <div id="today-content"></div>
          
        </section>
        <section>
          <h2>Неделя</h2>
          <div id="week-content"></div>
          
        </section>
      </div>
    </main>
    <script>
      const THEME_KEY = "miet_theme";
      const FONT_KEY = "miet_font";
      const root = document.documentElement;
      const toggle = document.getElementById("theme-toggle");
      const fontToggle = document.getElementById("font-toggle");

      function setTheme(name) {
        if (name === "light") {
          root.removeAttribute("data-theme");
        } else {
          root.setAttribute("data-theme", name);
        }
        localStorage.setItem(THEME_KEY, name);
        const buttons = toggle.querySelectorAll("button");
        buttons.forEach((btn) => {
          btn.classList.toggle("active", btn.dataset.theme === name);
        });
      }

      const savedTheme = localStorage.getItem(THEME_KEY) || "dark-blue";
      setTheme(savedTheme);

      function setFont(name) {
        const value = name === "montserrat" ? "Montserrat" : "Inter";
        root.style.setProperty("--font-body", `"${value}", "Segoe UI", sans-serif`);
        localStorage.setItem(FONT_KEY, name);
        const buttons = fontToggle.querySelectorAll("button");
        buttons.forEach((btn) => {
          btn.classList.toggle("active", btn.dataset.font === name);
        });
      }

      const savedFont = localStorage.getItem(FONT_KEY) || "inter";
      setFont(savedFont);

      toggle.addEventListener("click", (event) => {
        const button = event.target.closest("button[data-theme]");
        if (!button) return;
        setTheme(button.dataset.theme);
      });

      fontToggle.addEventListener("click", (event) => {
        const button = event.target.closest("button[data-font]");
        if (!button) return;
        setFont(button.dataset.font);
      });

      function renderTable(target, lessons) {
        if (!lessons || lessons.length === 0) {
          target.innerHTML = '<div class="empty">Нет занятий.</div>';
          return;
        }
        const table = document.createElement("table");
        table.innerHTML = `
          <thead>
            <tr>
              <th class="col-lesson">Пара</th>
              <th class="col-time">Время</th>
              <th class="col-subject">Дисциплина</th>
              <th class="col-type">Тип</th>
              <th class="col-teacher">Преподаватель</th>
              <th class="col-room">Аудитория</th>
            </tr>
          </thead>
          <tbody></tbody>
        `;
        const body = table.querySelector("tbody");
        for (const lesson of lessons) {
          const row = document.createElement("tr");
          row.innerHTML = `
            <td class="col-lesson">${lesson.lesson || ""}</td>
            <td class="col-time">${lesson.time || ""}</td>
            <td class="col-subject">${lesson.subject || ""}</td>
            <td class="col-type">${lesson.type || ""}</td>
            <td class="col-teacher">${lesson.teacher || ""}</td>
            <td class="col-room">${lesson.room || ""}</td>
          `;
          body.appendChild(row);
        }
        const wrap = document.createElement("div");
        wrap.className = "table-wrap";
        wrap.appendChild(table);
        target.innerHTML = "";
        target.appendChild(wrap);
      }

      function renderWeek(target, days) {
        if (!days || days.length === 0) {
          target.innerHTML = '<div class="empty">Нет занятий на этой неделе.</div>';
          return;
        }
        target.innerHTML = "";
        for (const day of days) {
          const title = document.createElement("h3");
          title.textContent = day.label;
          target.appendChild(title);
          const container = document.createElement("div");
          renderTable(container, day.lessons || []);
          target.appendChild(container);
        }
      }

      let weekOffset = 0;
      let currentWeekIndex = 0;
      let weekCycle = 1;

      function weekParam() {
        return weekOffset === 0 ? "" : `?week=${weekOffset}`;
      }

      function updateNav() {
        const prev = document.getElementById("prev-week");
        if (weekCycle > 1) {
          const minOffset = -currentWeekIndex;
          prev.disabled = weekOffset <= minOffset;
        } else {
          prev.disabled = false;
        }
      }

      async function load(mode) {
        const target = document.getElementById(mode + "-content");
        target.innerHTML = '<div class="empty">Загрузка...</div>';

        const resp = await fetch(`/api/${mode}${weekParam()}`);
        const data = await resp.json();

        if (!data.ok) {
          target.innerHTML = `<div class="error">${data.error || "Ошибка получения расписания."}</div>`;
          return;
        }

        if (typeof data.week_index === "number") {
          currentWeekIndex = data.week_index;
        }
        if (typeof data.week_cycle === "number") {
          weekCycle = data.week_cycle;
        }
        updateNav();

        const label = document.getElementById("week-label");
        if (data.today_label) {
          const todayLabel = document.getElementById("today-label");
          if (todayLabel) {
            todayLabel.textContent = data.today_label;
          }
        }

        if (data.week_number && data.week_label_view) {
          const first = `${data.week_number} неделя`;
          const second = data.week_label_view;
          label.innerHTML = `
            <div class="week-card">
              <div class="lines">
                <div>${first}</div>
                <div>${second}</div>
              </div>
            </div>
          `;
        } else {
          label.textContent = "";
        }

        if (mode === "today") {
          renderTable(target, data.lessons || []);
        } else {
          renderWeek(target, data.days || []);
        }

      }

      load("today");
      load("week");

      document.getElementById("prev-week").addEventListener("click", () => {
        weekOffset -= 1;
        load("today");
        load("week");
      });

      document.getElementById("next-week").addEventListener("click", () => {
        weekOffset += 1;
        load("today");
        load("week");
      });
    </script>
  </body>
</html>
"""


def _cache_get(key: str):
    entry = _cache.get(key)
    if not entry:
        return None
    if time.time() - entry.ts > CACHE_TTL_SECONDS:
        _cache.pop(key, None)
        return None
    return entry.value


def _cache_set(key: str, value: object) -> None:
    _cache[key] = CacheEntry(ts=time.time(), value=value)


def _now_local() -> datetime:
    return datetime.utcnow() + timedelta(hours=TIMEZONE_OFFSET)


def _week_start_date() -> date:
    value = WEEK_START_STR.replace(".", "-")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise RuntimeError("MIET_WEEK_START должен быть в формате YYYY-MM-DD.") from exc


def _post_schedule(group: str, cookie: str | None = None) -> tuple[str, dict]:
    data = urlparse.urlencode({"group": group}).encode("utf-8")
    headers = {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://miet.ru",
        "Referer": SCHEDULE_PAGE_URL,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36",
    }
    if cookie:
        headers["Cookie"] = cookie
    req = urlrequest.Request(
        SCHEDULE_DATA_URL,
        data=data,
        headers=headers,
        method="POST",
    )
    with urlrequest.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        text = resp.read().decode("utf-8", errors="ignore")
        resp_headers = dict(resp.headers.items())
    return text, resp_headers


def _extract_cookie(text: str, headers: dict) -> str | None:
    for key in ("Set-Cookie", "set-cookie"):
        value = headers.get(key)
        if value and "wl=" in value:
            return value.split(";", 1)[0] + ";path=/"
    match = re.search(r"(wl=[^;]+;path=/)", text)
    if match:
        return match.group(1)
    match = re.search(r"(wl=[^;]+)", text)
    if match:
        return match.group(1) + ";path=/"
    return None


def _load_schedule_json(group: str) -> dict:
    cached = _cache_get(f"raw:{group}")
    if cached:
        return cached

    text, headers = _post_schedule(group)
    payload = text.lstrip("\ufeff").strip()
    try:
        data = json.loads(payload)
        _cache_set(f"raw:{group}", data)
        return data
    except json.JSONDecodeError:
        cookie = _extract_cookie(payload, headers)
        if not cookie:
            raise RuntimeError("Не удалось получить расписание: неожиданный ответ.")
        text, _ = _post_schedule(group, cookie=cookie)
        payload = text.lstrip("\ufeff").strip()
        data = json.loads(payload)
        _cache_set(f"raw:{group}", data)
        return data


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_time(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 1_000_000_000_000 else value
        return datetime.utcfromtimestamp(seconds).strftime("%H:%M")
    if isinstance(value, str):
        match = re.search(r"/Date\\((\\d+)\\)/", value)
        if match:
            seconds = int(match.group(1)) / 1000
            return datetime.utcfromtimestamp(seconds).strftime("%H:%M")
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt.strftime("%H:%M")
        except ValueError:
            match = re.search(r"(\\d{1,2}:\\d{2})", value)
            return match.group(1) if match else value
    return str(value)


def _extract_date_value(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 1_000_000_000_000 else value
        dt = datetime.utcfromtimestamp(seconds)
        return dt.date() if dt.year >= 2000 else None
    if isinstance(value, str):
        match = re.search(r"/Date\\((\\d+)\\)/", value)
        if match:
            seconds = int(match.group(1)) / 1000
            dt = datetime.utcfromtimestamp(seconds)
            return dt.date() if dt.year >= 2000 else None
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt.date() if dt.year >= 2000 else None
        except ValueError:
            match = re.search(r"(\\d{4}-\\d{2}-\\d{2})", value)
            if match:
                try:
                    return date.fromisoformat(match.group(1))
                except ValueError:
                    return None
    return None


def _extract_entry_date(item: dict) -> date | None:
    for key in ("Date", "DateTime", "DateFrom", "DateTo"):
        if key in item:
            found = _extract_date_value(item.get(key))
            if found:
                return found
    time_block = item.get("Time") or {}
    for key in ("Date", "TimeFrom", "TimeTo"):
        if key in time_block:
            found = _extract_date_value(time_block.get(key))
            if found:
                return found
    return None


def _split_subject(name: str) -> tuple[str, str]:
    if not name:
        return "", ""
    tags = re.findall(r"\[(.+?)]", name)
    cleaned = re.sub(r"\s*\[(.+?)]\s*", " ", name).strip()
    lesson_type = tags[-1].strip() if tags else ""
    return cleaned, lesson_type


def _parse_entries(data: dict) -> list[dict]:
    entries = []
    for item in data.get("Data", []):
        time_block = item.get("Time") or {}
        lesson = {
            "day": _to_int(item.get("Day")),
            "week": _to_int(item.get("DayNumber")),
            "lesson_number": re.sub(
                r"\s*пара\s*$",
                "",
                str(time_block.get("Time") or "").strip(),
                flags=re.IGNORECASE,
            ),
            "start": _extract_time(time_block.get("TimeFrom")),
            "end": _extract_time(time_block.get("TimeTo")),
            "subject_raw": (item.get("Class") or {}).get("Name") or "",
            "teacher": (item.get("Class") or {}).get("TeacherFull") or "",
            "room": (item.get("Room") or {}).get("Name") or "",
            "date": _extract_entry_date(item),
        }
        subject, lesson_type = _split_subject(lesson["subject_raw"])
        lesson["subject"] = subject
        lesson["type"] = lesson_type
        if _should_skip_lesson(lesson):
            continue
        entries.append(lesson)
    return entries


def _should_skip_lesson(lesson: dict) -> bool:
    subject = lesson.get("subject") or ""
    room = lesson.get("room") or ""
    lesson_number = str(lesson.get("lesson_number") or "")
    if (
        "Финансовая грамотность в условиях цифровой экономики" in subject
        and "Виртуальная аудитория 1" in room
    ):
        return True
    if (
        lesson.get("day") == 6
        and "8" in lesson_number
        and "Финансовая грамотность в условиях цифровой экономики" in subject
    ):
        return True
    return False


def _week_meta(entries: list[dict]) -> dict:
    week_values = sorted({e["week"] for e in entries if e["week"] is not None})
    if not week_values:
        return {"cycle": 1, "shift": 0, "labels": ["Неделя"]}
    cycle = len(week_values)
    cycle = cycle if cycle in (2, 4) else max(cycle, 1)
    min_value = min(week_values)
    expected = list(range(min_value, min_value + cycle))
    shift = -min_value if week_values == expected else 0
    if cycle == 4:
        labels = ["1 числитель", "1 знаменатель", "2 числитель", "2 знаменатель"]
    elif cycle == 2:
        labels = ["числитель", "знаменатель"]
    else:
        labels = [f"Неделя {i + 1}" for i in range(cycle)]
    return {"cycle": cycle, "shift": shift, "labels": labels}


def _normalize_week_value(value, meta: dict) -> int | None:
    if value is None:
        return None
    number = None
    if isinstance(value, (int, float)):
        number = int(value)
    elif isinstance(value, str):
        match = re.search(r"(\d+)", value)
        if match:
            number = int(match.group(1))
        else:
            lowered = value.lower()
            if "числ" in lowered and meta["cycle"] >= 2:
                return 0
            if "знам" in lowered and meta["cycle"] >= 2:
                return 1
    if number is None or number <= 0:
        return None
    if meta["cycle"] <= 0:
        return None
    return (number + meta["shift"]) % meta["cycle"]


def _override_week_index(meta: dict) -> int | None:
    if not WEEK_OVERRIDE:
        return None
    value = WEEK_OVERRIDE.lower().strip()
    cycle = max(meta.get("cycle", 1), 1)
    match = re.search(r"(\\d+)", value)
    if match:
        number = int(match.group(1))
        if 1 <= number <= cycle:
            return number - 1
    if "числ" in value:
        if "2" in value and cycle >= 4:
            return 2
        return 0
    if "знам" in value:
        if "2" in value and cycle >= 4:
            return 3
        return 1 if cycle >= 2 else 0
    return None


def _extract_week_label(data: dict) -> str:
    if not isinstance(data, dict):
        return ""
    for key in (
        "WeekName",
        "WeekLabel",
        "WeekText",
        "CurrentWeekText",
        "WeekNow",
        "Week",
        "WeekNumber",
        "WeekNum",
        "CurrentWeek",
        "WeekIndex",
        "WeekNumberNow",
        "CurrentWeekNumber",
        "WeekNumberCurrent",
    ):
        if key in data and data.get(key) is not None:
            return str(data.get(key)).strip()
    return ""


def _current_week_index(meta: dict, today: date, data: dict) -> int:
    forced = _override_week_index(meta)
    if forced is not None:
        return forced
    label = _extract_week_label(data)
    if label:
        label_index = _normalize_week_value(label, meta)
        if label_index is not None:
            return (label_index + WEEK_SHIFT) % meta["cycle"] if meta["cycle"] > 0 else label_index
    try:
        start = _week_start_date()
        base_monday = start - timedelta(days=start.weekday())
        current_monday = today - timedelta(days=today.weekday())
        weeks_since = (current_monday - base_monday).days // 7
        if meta["cycle"] > 0:
            return (weeks_since + WEEK_SHIFT) % meta["cycle"]
        return max(weeks_since, 0)
    except Exception:
        pass
    for key in (
        "Week",
        "WeekNumber",
        "WeekNum",
        "CurrentWeek",
        "WeekIndex",
        "WeekNumberNow",
        "CurrentWeekNumber",
        "WeekNumberCurrent",
    ):
        if isinstance(data, dict) and key in data:
            candidate = _normalize_week_value(data.get(key), meta)
            if candidate is not None:
                index = candidate
                break
    else:
        index = None

    week_number = today.isocalendar().week
    if index is None:
        if meta["cycle"] <= 0:
            index = 0
        else:
            index = (week_number - 1) % meta["cycle"]

    if meta["cycle"] > 0:
        index = (index + WEEK_SHIFT) % meta["cycle"]
    return index


def _auto_week_index(entries: list[dict], meta: dict, today: date, data: dict) -> int:
    index = _current_week_index(meta, today, data)
    cycle = meta.get("cycle", 1)
    if cycle <= 1:
        return index
    day_number = today.isoweekday()
    counts = []
    for idx in range(cycle):
        count = sum(
            1
            for e in entries
            if e["day"] == day_number
            and ((e["week"] + meta["shift"]) % cycle) == idx
        )
        counts.append(count)
    max_count = max(counts) if counts else 0
    if max_count > 0:
        candidates = [i for i, c in enumerate(counts) if c == max_count]
        if len(candidates) == 1:
            return candidates[0]
    return index


def _linear_week_number(today: date, week_offset: int = 0) -> int:
    start = _week_start_date()
    base_monday = start - timedelta(days=start.weekday())
    current_monday = today - timedelta(days=today.weekday())
    weeks_since = (current_monday - base_monday).days // 7
    return max(weeks_since + 1 + week_offset, 1)


def _format_lesson(entry: dict) -> dict:
    time_label = entry["start"]
    if entry["end"]:
        time_label = f"{entry['start']}\n{entry['end']}"
    room = entry.get("room", "")
    if "Виртуальная аудитория" in room:
        room = "Онлайн"
    return {
        "lesson": entry.get("lesson_number", ""),
        "time": time_label,
        "subject": entry.get("subject", ""),
        "type": entry.get("type", ""),
        "teacher": entry.get("teacher", ""),
        "room": room,
    }


def _get_schedule(group: str) -> dict:
    cached = _cache_get(f"parsed:{group}")
    if cached:
        return cached
    data = _load_schedule_json(group)
    entries = _parse_entries(data)
    meta = _week_meta(entries)
    has_dates = any(e["date"] for e in entries)
    payload = {"entries": entries, "meta": meta, "has_dates": has_dates, "raw": data}
    _cache_set(f"parsed:{group}", payload)
    return payload


def _get_group() -> str:
    group = request.args.get("group", "").strip()
    return group or DEFAULT_GROUP


def _get_week_offset() -> int:
    raw = request.args.get("week", "").strip()
    if not raw:
        return 0
    try:
        return int(raw)
    except ValueError:
        return 0


def _day_label(day_index: int, day_date: date | None = None) -> str:
    names = {
        1: "Понедельник",
        2: "Вторник",
        3: "Среда",
        4: "Четверг",
        5: "Пятница",
        6: "Суббота",
        0: "Воскресенье",
    }
    label = names.get(day_index, "")
    if day_date:
        return f"{label}, {day_date.strftime('%d.%m')}"
    return label


@app.get("/")
def index():
    return render_template_string(
        INDEX_HTML,
        group=DEFAULT_GROUP,
    )


@app.get("/api/today")
def api_today():
    group = _get_group()
    if not group:
        return jsonify(
            ok=False,
            error="Группа не задана. Укажи MIET_GROUP в переменных окружения.",
        )
    try:
        schedule = _get_schedule(group)
        entries = schedule["entries"]
        meta = schedule["meta"]
        today = _now_local().date()
        week_offset = _get_week_offset()
        if schedule["has_dates"]:
            target_date = today + timedelta(days=week_offset * 7)
            lessons = [e for e in entries if e["date"] == target_date]
            now_label = ""
            view_label = target_date.strftime("%d.%m")
            today_label = _day_label(target_date.isoweekday(), target_date)
            week_index = 0
        else:
            week_index = _auto_week_index(
                entries,
                meta,
                today,
                schedule.get("raw", {}),
            )
            if meta["cycle"] > 0:
                week_index = (week_index + week_offset) % meta["cycle"]
            now_label = _extract_week_label(schedule.get("raw", {})) or meta["labels"][week_index]
            view_label = meta["labels"][week_index]
            today_label = _day_label(today.isoweekday(), today)
            day_number = today.isoweekday()
            lessons = [
                e
                for e in entries
                if e["day"] == day_number
                and ((e["week"] + meta["shift"]) % meta["cycle"]) == week_index
            ]
        lessons = sorted(
            lessons,
            key=lambda x: (x.get("lesson_number") or "", x.get("start") or ""),
        )
        return jsonify(
            ok=True,
            group=group,
            week_label_now=now_label,
            week_label_view=view_label,
            week_index=week_index,
            week_number=_linear_week_number(today, week_offset),
            week_cycle=meta["cycle"],
            today_label=today_label,
            lessons=[_format_lesson(e) for e in lessons],
        )
    except Exception as exc:
        return jsonify(ok=False, error=str(exc))


@app.get("/api/week")
def api_week():
    group = _get_group()
    if not group:
        return jsonify(
            ok=False,
            error="Группа не задана. Укажи MIET_GROUP в переменных окружения.",
        )
    try:
        schedule = _get_schedule(group)
        entries = schedule["entries"]
        meta = schedule["meta"]
        today = _now_local().date()
        week_offset = _get_week_offset()
        days = []
        week_label = ""
        if schedule["has_dates"]:
            reference = today + timedelta(days=week_offset * 7)
            monday = reference - timedelta(days=reference.weekday())
            sunday = monday + timedelta(days=7)
            week_entries = [
                e
                for e in entries
                if e["date"] and monday <= e["date"] < sunday
            ]
            for day_index in range(1, 7):
                day_date = monday + timedelta(days=day_index - 1)
                day_lessons = [
                    e for e in week_entries if e["date"] == day_date
                ]
                day_lessons.sort(
                    key=lambda x: (x.get("lesson_number") or "", x.get("start") or "")
                )
                days.append(
                    {
                        "label": _day_label(day_index, day_date),
                        "lessons": [_format_lesson(e) for e in day_lessons],
                    }
                )
            now_label = ""
            view_label = f"{monday.strftime('%d.%m')}–{(sunday - timedelta(days=1)).strftime('%d.%m')}"
            week_index = 0
        else:
            week_index = _auto_week_index(
                entries,
                meta,
                today,
                schedule.get("raw", {}),
            )
            if meta["cycle"] > 0:
                week_index = (week_index + week_offset) % meta["cycle"]
            now_label = _extract_week_label(schedule.get("raw", {})) or meta["labels"][week_index]
            view_label = meta["labels"][week_index]
            reference = today + timedelta(days=week_offset * 7)
            monday = reference - timedelta(days=reference.weekday())
            for day_index in range(1, 7):
                day_date = monday + timedelta(days=day_index - 1)
                day_lessons = [
                    e
                    for e in entries
                    if e["day"] == day_index
                    and ((e["week"] + meta["shift"]) % meta["cycle"]) == week_index
                ]
                day_lessons.sort(
                    key=lambda x: (x.get("lesson_number") or "", x.get("start") or "")
                )
                days.append(
                    {
                        "label": _day_label(day_index, day_date),
                        "lessons": [_format_lesson(e) for e in day_lessons],
                    }
                )
        return jsonify(
            ok=True,
            group=group,
            week_label_now=now_label,
            week_label_view=view_label,
            week_index=week_index,
            week_number=_linear_week_number(today, week_offset),
            week_cycle=meta["cycle"],
            days=days,
        )
    except Exception as exc:
        return jsonify(ok=False, error=str(exc))


@app.get("/api/debug")
def api_debug():
    group = _get_group()
    if not group:
        return jsonify(ok=False, error="Группа не задана.")
    try:
        data = _load_schedule_json(group)
        return jsonify(ok=True, raw=data)
    except Exception as exc:
        return jsonify(ok=False, error=str(exc))


if __name__ == "__main__":
    host = os.getenv("MIET_HOST", "127.0.0.1")
    port = int(os.getenv("MIET_PORT", "5000"))
    app.run(host=host, port=port, debug=True)
