"""
fetch_calendar.py

Downloads your Google Calendar (its public iCal/.ics link), works out the
events coming up in the next couple of weeks, and writes them to
docs/calendar.json. The dashboard page calendar.html reads that file.

WHY THIS SCRIPT EXISTS: a web page on GitHub Pages isn't allowed to read
your Google Calendar link directly (browsers block it for security). A
script can, so this script does the fetching and saves the result as a
plain file the page CAN read.

You normally DON'T run this by hand. A GitHub "Action" (see
.github/workflows/calendar.yml) runs it every 30 minutes and saves any
changes to your repo automatically.

To test it on your own computer:
    pip install icalendar recurring-ical-events
    python fetch_calendar.py
"""

import json
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import icalendar
import recurring_ical_events


# =============================================================================
# CONFIG -- edit these values
# =============================================================================

BASE_DIR = Path(__file__).resolve().parent

# Paste your calendar's PUBLIC iCal link here (keep the quotes).
# In Google Calendar: Settings > your calendar > "Integrate calendar" >
# "Public address in iCal format". It ends in .ics
#
# IMPORTANT: use the PUBLIC address, NOT the "Secret address in iCal format".
# This repo is public, so anyone can read this file; the secret address
# would let anyone see your whole calendar.
CALENDAR_SOURCE = "https://calendar.google.com/calendar/ical/f5a92e8edca77b53dffbef7cb9c8aae7c8e0e0937e4ec0f580822bc4ad0996b1%40group.calendar.google.com/public/basic.ics"

# Your time zone, so "9:00 AM" means 9:00 AM in Arizona.
# (Arizona doesn't do daylight saving time.)
TIMEZONE = "America/Phoenix"

# How many days ahead to include (including today).
DAYS_AHEAD = 14

# Where to write the data file that calendar.html reads.
JSON_OUTPUT_PATH = BASE_DIR / "docs" / "calendar.json"


# =============================================================================
# LOGIC -- you shouldn't need to edit below here.
# =============================================================================


def load_calendar_text(source):
    """
    Get the raw calendar text, either from a web link or from a file on
    this computer (handy for testing).
    """
    if source.startswith("PASTE_YOUR"):
        sys.exit("ERROR: Open fetch_calendar.py and paste your iCal link into CALENDAR_SOURCE.")

    # Some calendar apps give "webcal://" links; that is just "https://" in disguise
    if source.startswith("webcal://"):
        source = "https://" + source[len("webcal://"):]

    if source.startswith("http"):
        request = Request(source, headers={"User-Agent": "classroom-dashboard"})
        with urlopen(request, timeout=30) as response:
            return response.read()
    return Path(source).read_bytes()


def to_local(dt, tz):
    """
    Convert a date-and-time to our time zone. Some calendar entries have no
    time zone attached ("floating" times); we assume those are already local.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def build_events(calendar, tz):
    """
    Make a simple list of events for the next DAYS_AHEAD days.
    Each event is a small dictionary with a title, date, and times.

    The recurring_ical_events library does the hard part: if you have a
    "repeats every Monday" event, it works out each actual Monday for us.
    """
    today = datetime.now(tz).date()
    last_day = today + timedelta(days=DAYS_AHEAD - 1)
    window_start = datetime.combine(today, time.min, tzinfo=tz)
    window_end = datetime.combine(last_day + timedelta(days=1), time.min, tzinfo=tz)

    # skip_bad_series=True means one broken event can't crash the whole job;
    # it just gets left out. (Very old versions of the library don't have this
    # option, so we fall back to the plain version if needed.)
    try:
        query = recurring_ical_events.of(calendar, skip_bad_series=True)
    except TypeError:
        query = recurring_ical_events.of(calendar)
    raw_events = query.between(window_start, window_end)

    events = []
    for event in raw_events:
        # Skip events you cancelled
        if str(event.get("STATUS", "")).upper() == "CANCELLED":
            continue

        title = str(event.get("SUMMARY", "(no title)")).strip()
        start = event["DTSTART"].dt
        end_property = event.get("DTEND")
        end = end_property.dt if end_property is not None else None

        # NOTE: a datetime counts as a date too, so we must check datetime first.
        if isinstance(start, datetime):
            # ----- An event with a start time -----
            start = to_local(start, tz)
            end = to_local(end, tz) if isinstance(end, datetime) else None
            # Only keep the end time if the event ends the same day it starts
            same_day_end = end is not None and end.date() == start.date() and end > start
            events.append({
                "title": title,
                "date": start.date().isoformat(),
                "all_day": False,
                "start_time": start.strftime("%H:%M"),
                "end_time": end.strftime("%H:%M") if same_day_end else None,
            })
        else:
            # ----- An all-day event (possibly several days long) -----
            # Note: the end date of an all-day event is the day
            # AFTER it finishes, so we stop before it.
            if end is None:
                end = start + timedelta(days=1)
            day = start
            while day < end:
                if today <= day <= last_day:
                    events.append({
                        "title": title,
                        "date": day.isoformat(),
                        "all_day": True,
                        "start_time": None,
                        "end_time": None,
                    })
                day += timedelta(days=1)

    # Sort by day, with all-day events first, then by start time
    events.sort(key=lambda e: (e["date"], not e["all_day"], e["start_time"] or ""))
    return events


def write_json_if_changed(events, output_path):
    """
    Save the events as JSON. If nothing changed since last time, leave the
    file alone, so the automatic job doesn't create a pointless new commit
    every 30 minutes.
    """
    new_text = json.dumps({"timezone": TIMEZONE, "events": events}, indent=2)
    output_path = Path(output_path)

    if output_path.exists() and output_path.read_text(encoding="utf-8") == new_text:
        print("Calendar unchanged. Nothing to write.")
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(new_text, encoding="utf-8")
    print(f"Wrote {len(events)} events to: {output_path}")


def main():
    # Optional: "python fetch_calendar.py some_file.ics" reads a local file instead
    source = sys.argv[1] if len(sys.argv) > 1 else CALENDAR_SOURCE

    tz = ZoneInfo(TIMEZONE)
    calendar = icalendar.Calendar.from_ical(load_calendar_text(source))
    events = build_events(calendar, tz)

    print(f"Found {len(events)} events in the next {DAYS_AHEAD} days.")
    write_json_if_changed(events, JSON_OUTPUT_PATH)


if __name__ == "__main__":
    main()
