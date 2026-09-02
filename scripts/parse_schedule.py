#!/usr/bin/env python3
"""Parse the VIEW Conference live schedule HTML (view_CET.html) into structured JSON.

Usage: python3 parse_schedule.py <input.html> <output.json>

Fetch the input first, e.g.:
  curl -s -A "Mozilla/5.0" -o view_CET.html \
    https://www.viewconference.it/assets/html/view_CET.html
"""
import re
import json
import sys
from datetime import datetime, timezone
from bs4 import BeautifulSoup

SOURCE_URL = "https://www.viewconference.it/assets/html/view_CET.html"

MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}

LIGHT_PASS_TYPES = {"talk", "panel", "keynote"}

DROP_TOKEN_RE = re.compile(r'^\d', re.IGNORECASE)
DROP_WORDS = {"hour", "hours", "day", "days", "over", "long", "-", "over,"}


def extract_type(bracket_text: str):
    """'4-hour Workshop in English' -> ('Workshop', '4-hour', 'English')"""
    m = re.match(r'^(.*?)\s+in\s+([A-Za-z]+)\s*$', bracket_text.strip())
    if m:
        type_part, language = m.group(1), m.group(2)
    else:
        type_part, language = bracket_text.strip(), None

    tokens = type_part.split()
    kept = []
    duration_tokens = []
    for tok in tokens:
        bare = tok.strip(",-").lower()
        if DROP_TOKEN_RE.match(tok) or bare in DROP_WORDS:
            duration_tokens.append(tok)
        else:
            kept.append(tok)
    type_clean = " ".join(kept).strip() or type_part.strip()
    duration_note = " ".join(duration_tokens).strip() or None
    return type_clean, duration_note, language


def norm_ws(text: str) -> str:
    return re.sub(r'\s+', ' ', text).strip()


def find_conference_year_month(soup) -> tuple:
    """Look for '#viewconference2026' and 'DD-DD MON' in the page header text."""
    full_text = soup.get_text(" ")
    year_m = re.search(r'#viewconference(\d{4})', full_text)
    month_m = re.search(r'\d{1,2}\s*-\s*\d{1,2}\s+([A-Z]{3,})', full_text)
    year = int(year_m.group(1)) if year_m else datetime.now().year
    month = MONTHS.get(month_m.group(1)[:3].upper(), datetime.now().month) if month_m else datetime.now().month
    return year, month


def day_label_to_iso(day_label: str, year: int, month: int) -> str:
    """'Mon 12' -> '2026-10-12'. Falls back to the raw label if unparseable."""
    m = re.search(r'(\d{1,2})', day_label or "")
    if not m:
        return day_label
    day = int(m.group(1))
    try:
        return datetime(year, month, day).date().isoformat()
    except ValueError:
        return day_label


def parse(html: str):
    soup = BeautifulSoup(html, "lxml")
    sessions = []
    days = []

    year, month = find_conference_year_month(soup)

    schedule_divs = soup.find_all("div", class_=re.compile(r'^schedule\d+$'))
    for sdiv in schedule_divs:
        track_spans = sdiv.find_all("span", class_="track-slot", recursive=False)
        day_label = None
        room_by_track = {}
        for span in track_spans:
            style = span.get("style", "")
            text = span.get_text(strip=True)
            m = re.search(r'grid-column:\s*(times|track-\d+)', style)
            if not m:
                continue
            col = m.group(1)
            if col == "times":
                day_label = text
            else:
                room_by_track[col] = text

        date_iso = day_label_to_iso(day_label, year, month)
        days.append({"date": date_iso, "label": day_label, "rooms": list(room_by_track.values())})

        for sess in sdiv.find_all("div", class_=re.compile(r'\bsession\b')):
            classes = sess.get("class", [])
            sess_id = next((c for c in classes if re.match(r'^session-\d+$', c)), None)
            track_class = next((c for c in classes if re.match(r'^track-\d+$', c)), None)
            room = room_by_track.get(track_class, "TBD")

            title_tag = sess.find("h3", class_="session-title")
            title = norm_ws(title_tag.get_text(" ", strip=True)) if title_tag else "Untitled Session"
            link_tag = title_tag.find("a") if title_tag else None
            article_url = link_tag["href"] if link_tag else None

            time_span = sess.find("span", class_="session-time")
            time_raw = ""
            room_mode = "In Person"
            if time_span:
                room_sub = time_span.find("span", class_="session-room")
                room_mode_text = room_sub.get_text(strip=True) if room_sub else ""
                m2 = re.search(r'\(([^)]+)\)', room_mode_text)
                if m2:
                    room_mode = m2.group(1)
                full_text = time_span.get_text(" ", strip=True)
                if room_sub:
                    full_text = full_text.replace(room_sub.get_text(" ", strip=True), "").strip()
                time_raw = full_text

            m3 = re.match(r'(\d{2}:\d{2})-(\d{2}:\d{2})\s*CET\s*\[(.*?)\]', time_raw)
            time_start = time_end = None
            type_clean = duration_note = language = None
            if m3:
                time_start, time_end, bracket = m3.groups()
                type_clean, duration_note, language = extract_type(bracket)
            else:
                # Unparseable time/type: keep the session visible instead of dropping it,
                # but never let a None sneak into time-based sort/group/overlap logic downstream.
                type_clean = "Session"

            speakers = []
            pending_moderator = False
            for child in sess.find_all(["span", "div"], recursive=False):
                child_classes = child.get("class") or []
                if child.name == "span" and "session-presenter" in child_classes:
                    a = child.find("a")
                    role_span = child.find("span", class_="session-presenter-title")
                    role_text = norm_ws(role_span.get_text(" ", strip=True)) if role_span else ""
                    if a:
                        name = norm_ws(a.get_text(" ", strip=True))
                        url = a.get("href")
                    else:
                        raw = norm_ws(child.get_text(" ", strip=True))
                        name = raw.split(role_text)[0].strip().rstrip(",") if role_text else raw
                        url = None
                    speakers.append({
                        "name": name,
                        "role": role_text,
                        "url": url,
                        "isModerator": pending_moderator,
                    })
                    pending_moderator = False
                elif child.name == "span" and child.get_text(strip=True) == "Moderator":
                    pending_moderator = True

            notes = []
            for div_child in sess.find_all("div", recursive=False):
                note_text = norm_ws(div_child.get_text(" ", strip=True))
                if note_text:
                    notes.append(note_text)

            # Ticket access is 3-valued: a "(Separate Ticket)" note overrides pass type
            # entirely (neither pass includes it on its own); otherwise Light Pass covers
            # only Talk/Panel/Keynote per the site's own note, everything else is All Access.
            has_separate_ticket = any(re.search(r'separate ticket', n, re.IGNORECASE) for n in notes)
            if has_separate_ticket:
                ticket_access = "separate"
            elif (type_clean or "").lower() in LIGHT_PASS_TYPES:
                ticket_access = "light"
            else:
                ticket_access = "all"

            sessions.append({
                "id": sess_id or f"session-{len(sessions)}",
                "day": date_iso,
                "dayLabel": day_label,
                "title": title,
                "articleUrl": article_url,
                "type": type_clean,
                "durationNote": duration_note,
                "language": language,
                "timeStart": time_start,
                "timeEnd": time_end,
                "room": room,
                "venueMode": room_mode,
                "ticketAccess": ticket_access,
                "speakers": speakers,
                "notes": notes,
            })

    seen = set()
    uniq_days = []
    for d in days:
        if d["date"] not in seen:
            seen.add(d["date"])
            uniq_days.append(d)

    speaker_map = {}
    for s in sessions:
        for sp in s["speakers"]:
            key = sp["url"] or sp["name"]
            entry = speaker_map.setdefault(key, {
                "name": sp["name"],
                "url": sp["url"],
                "roles": [],
                "sessionIds": [],
            })
            if sp["role"] and sp["role"] not in entry["roles"]:
                entry["roles"].append(sp["role"])
            entry["sessionIds"].append(s["id"])

    speakers_dir = sorted(speaker_map.values(), key=lambda x: x["name"])

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sourceUrl": SOURCE_URL,
        "days": uniq_days,
        "sessions": sessions,
        "speakers": speakers_dir,
    }


if __name__ == "__main__":
    in_path = sys.argv[1] if len(sys.argv) > 1 else "view_CET.html"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "schedule.json"
    with open(in_path, encoding="utf-8") as f:
        html = f.read()
    data = parse(html)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Parsed {len(data['sessions'])} sessions across {len(data['days'])} days, "
          f"{len(data['speakers'])} unique speakers -> {out_path}")
