import os
import re
import json
from datetime import datetime
from urllib.parse import urlencode
from urllib.request import urlopen

from fastmcp import FastMCP

mcp = FastMCP("UBS Stage 3")

API_BASE = os.environ.get("TEAM_API_BASE", "https://tool-box-2591eaa24fa3.herokuapp.com").rstrip("/")


# --------------------------
# Time helpers
# --------------------------

DAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DAY_SET = set(DAY_ORDER)
DAY_START = "08:00"
DAY_END = "23:00"  # end of day bound (exclusive in interval math)


def normalize_day(day: str) -> str:
    d = (day or "").strip()
    for name in DAY_ORDER:
        if d.lower() == name.lower():
            return name
    raise ValueError(f"Invalid day '{day}'. Use Monday..Sunday.")


def hhmm_to_minutes(hhmm: str) -> int:
    if not re.fullmatch(r"\d{2}:\d{2}", hhmm):
        raise ValueError(f"Invalid time format '{hhmm}'. Expected HH:MM.")
    hh, mm = map(int, hhmm.split(":"))
    if not (0 <= hh <= 23 and mm == 0):
        raise ValueError(f"Invalid time '{hhmm}'. Must be on the hour, 00 minutes.")
    return hh * 60 + mm


def minutes_to_hhmm(total: int) -> str:
    hh = total // 60
    mm = total % 60
    return f"{hh:02d}:{mm:02d}"


def overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start < b_end and b_start < a_end


# --------------------------
# HTTP helpers
# --------------------------

def http_get_json(path: str, params: dict | None = None) -> dict:
    url = f"{API_BASE}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    with urlopen(url, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_venues(day: str) -> list[dict]:
    payload = http_get_json(f"/venues/{day}")
    return payload.get("venues", [])


def get_schedule(person: str, day: str) -> list[tuple[str, str]]:
    payload = http_get_json(f"/schedule/{person}/{day}")
    return payload.get("busy", [])


def get_location(person: str, day: str) -> tuple[int, int]:
    payload = http_get_json(f"/location/{person}/{day}")
    return int(payload["x"]), int(payload["y"])


# --------------------------
# Inbox parser (android calendar)
# --------------------------

WHEN_RE = re.compile(
    r"When:\s*(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+(\d{2}:\d{2})-(\d{2}:\d{2})",
    re.IGNORECASE
)
RESP_RE = re.compile(r"Response:\s*(ACCEPTED|DECLINED|TENTATIVE)", re.IGNORECASE)


def parse_inbox_events(inbox_text: str, day: str) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """
    Returns:
      accepted_busy: intervals that block completely
      tentative_busy: intervals that are fallback-only conflicts
    """
    accepted_busy = []
    tentative_busy = []

    if not inbox_text:
        return accepted_busy, tentative_busy

    lines = inbox_text.splitlines()
    current_response = None

    for line in lines:
        r = RESP_RE.search(line)
        if r:
            current_response = r.group(1).upper()
            continue

        w = WHEN_RE.search(line)
        if w and current_response:
            w_day, st, en = w.group(1), w.group(2), w.group(3)
            if normalize_day(w_day) != day:
                continue

            s = hhmm_to_minutes(st)
            e = hhmm_to_minutes(en)
            if e <= s:
                continue

            if current_response == "ACCEPTED":
                accepted_busy.append((s, e))
            elif current_response == "TENTATIVE":
                tentative_busy.append((s, e))
            # DECLINED => no constraint

    return accepted_busy, tentative_busy


# --------------------------
# Core solvers
# --------------------------

def build_candidate_starts(range_start: str, range_end: str, duration_minutes: int) -> list[int]:
    rs = hhmm_to_minutes(range_start)
    re_ = hhmm_to_minutes(range_end)
    ds = hhmm_to_minutes(DAY_START)
    de = hhmm_to_minutes(DAY_END)

    if duration_minutes <= 0 or duration_minutes % 60 != 0:
        raise ValueError("duration_minutes must be a positive multiple of 60.")
    if rs < ds or re_ > de or rs >= re_:
        raise ValueError("Invalid range; must be within 08:00..23:00 and start < end.")

    starts = []
    t = rs
    while t + duration_minutes <= re_:
        starts.append(t)
        t += 60
    return starts


def interval_conflicts(start: int, end: int, intervals: list[tuple[int, int]]) -> bool:
    for s, e in intervals:
        if overlaps(start, end, s, e):
            return True
    return False


def pick_best_window(day: str, participants: list[str], range_start: str, range_end: str, duration_minutes: int, inbox_text: str) -> tuple[str, str]:
    day = normalize_day(day)
    starts = build_candidate_starts(range_start, range_end, duration_minutes)

    accepted_busy, tentative_busy = parse_inbox_events(inbox_text, day)

    # Add friends' busy
    all_busy = list(accepted_busy)
    for p in participants:
        for st, en in get_schedule(p, day):
            all_busy.append((hhmm_to_minutes(st), hhmm_to_minutes(en)))

    clean = []
    tentative_only = []

    for st in starts:
        en = st + duration_minutes
        if interval_conflicts(st, en, all_busy):
            continue
        if interval_conflicts(st, en, tentative_busy):
            tentative_only.append((st, en))
        else:
            clean.append((st, en))

    if clean:
        st, en = clean[0]
        return minutes_to_hhmm(st), minutes_to_hhmm(en)
    if tentative_only:
        st, en = tentative_only[0]
        return minutes_to_hhmm(st), minutes_to_hhmm(en)

    raise ValueError("No feasible meeting window in requested range.")


def manhattan(a: tuple[int, int], b: tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def best_meeting_point(day: str, me: list[int], participants: list[str]) -> list[int]:
    day = normalize_day(day)
    if len(me) != 2:
        raise ValueError("me must be [x, y].")

    me_xy = (int(me[0]), int(me[1]))
    points = [me_xy] + [get_location(p, day) for p in participants]

    best_cost = None
    best_cell = None

    for x in range(10):
        for y in range(10):
            c = (x, y)
            total = sum(manhattan(src, c) for src in points)
            if best_cost is None or total < best_cost:
                best_cost = total
                best_cell = c

    return [best_cell[0], best_cell[1]]


def venue_open_for_window(venue: dict, start_hhmm: str, duration_minutes: int) -> bool:
    st = hhmm_to_minutes(start_hhmm)
    en = st + duration_minutes
    for a, b in venue.get("available", []):
        avs = hhmm_to_minutes(a)
        ave = hhmm_to_minutes(b)
        if st >= avs and en <= ave:
            return True
    return False


# --------------------------
# MCP tools
# --------------------------

@mcp.tool()
def get_name() -> str:
    """Return the agent name."""
    return "BabyBot"


@mcp.tool()
def find_open_venues(day: str, time: str) -> str:
    """
    Return all venue names open at the specified day/time as a comma-separated string.
    """
    day = normalize_day(day)
    t = hhmm_to_minutes(time)

    names = []
    for v in get_venues(day):
        for a, b in v.get("available", []):
            s = hhmm_to_minutes(a)
            e = hhmm_to_minutes(b)
            if s <= t < e:
                names.append(v["name"])
                break

    return ", ".join(names)


@mcp.tool()
def find_best_meeting_window(
    day: str,
    participants: list[str],
    range_start: str,
    range_end: str,
    duration_minutes: int,
    inbox_text: str
) -> dict:
    """
    Find earliest best window:
      1) earliest clean window (no overlap with accepted/friends/tentative),
      2) if none exists, earliest window overlapping only tentative android commitments.
    Returns {"start":"HH:MM","end":"HH:MM"}.
    """
    st, en = pick_best_window(day, participants, range_start, range_end, duration_minutes, inbox_text)
    return {"start": st, "end": en}


@mcp.tool()
def find_best_meeting_point(day: str, my_position: list[int], participants: list[str]) -> list[int]:
    """
    Find [x, y] in 0..9 x 0..9 minimizing total Manhattan travel for you + all participants.
    """
    return best_meeting_point(day, my_position, participants)


@mcp.tool()
def plan_outing(
    day: str,
    my_position: list[int],
    participants: list[str],
    range_start: str,
    range_end: str,
    duration_minutes: int,
    inbox_text: str
) -> dict:
    """
    Solve full outing:
      - pick valid meeting window using tentative rules,
      - choose a venue open for [meeting_end, meeting_end + duration),
      - choose meeting point minimizing:
          sum(person->meeting_point for all, including android)
          + distance(meeting_point->venue)
    Returns:
      {
        "meeting_start":"HH:MM",
        "meeting_end":"HH:MM",
        "meeting_point":[x,y],
        "venue":"Name"
      }
    """
    day = normalize_day(day)
    if len(my_position) != 2:
        raise ValueError("my_position must be [x, y].")

    # 1) Must be the correct meeting window first
    meeting_start, meeting_end = pick_best_window(
        day=day,
        participants=participants,
        range_start=range_start,
        range_end=range_end,
        duration_minutes=duration_minutes,
        inbox_text=inbox_text
    )

    # 2) Venue must be open in hour beginning at meeting end (duration_minutes window)
    venues = get_venues(day)
    open_venues = [v for v in venues if venue_open_for_window(v, meeting_end, duration_minutes)]
    if not open_venues:
        raise ValueError("No venue is open for the required post-meeting window.")

    # 3) Minimize total journey
    me_xy = (int(my_position[0]), int(my_position[1]))
    people = [me_xy] + [get_location(p, day) for p in participants]

    best_total = None
    best_answer = None

    for x in range(10):
        for y in range(10):
            meeting_point = (x, y)
            inbound = sum(manhattan(src, meeting_point) for src in people)

            for v in open_venues:
                venue_xy = (int(v["x"]), int(v["y"]))
                total = inbound + manhattan(meeting_point, venue_xy)
                if best_total is None or total < best_total:
                    best_total = total
                    best_answer = {
                        "meeting_start": meeting_start,
                        "meeting_end": meeting_end,
                        "meeting_point": [x, y],
                        "venue": v["name"]
                    }

    return best_answer


app = mcp.http_app(path="/mcp")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))

    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=port,
        path="/mcp"
    )