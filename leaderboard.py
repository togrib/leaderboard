"""
leaderboard.py

Reads a Canvas gradebook CSV export, calculates a homework completion
percentage for each class period (Section), and writes out an HTML
leaderboard page. Optionally commits and pushes that HTML file to
GitHub so the classroom kiosk (Raspberry Pi) picks up the update.

HOW TO RUN:
    1. Export your gradebook CSV from Canvas.
    2. Edit the CONFIG section below (paths, names, etc.) if needed.
    3. Run:  python leaderboard.py

Everything you're likely to want to change lives in the CONFIG section
right below the imports. You shouldn't need to touch the functions
underneath unless you want to change *how* something works.
"""

import csv
import subprocess
import sys
from pathlib import Path


# =============================================================================
# CONFIG -- edit these values to match your setup. Nothing below this section
# should need to change for day-to-day use.
# =============================================================================

# This is the folder that this script itself lives in, figured out
# automatically -- NOT typed in by hand. That's what makes the paths below
# work correctly no matter which computer you run this from, as long as
# this script stays inside your cloned GitHub repo folder.
#
# SETUP (one time, per computer):
#   1. Create an empty repo on GitHub.com (e.g. "classroom-leaderboard").
#   2. On your computer, run: git clone <the repo's URL>
#      (This is also where you'll sign into GitHub -- git remembers that
#      login on this computer from then on, so the script never needs to
#      handle passwords or tokens itself.)
#   3. Move/save this leaderboard.py file INSIDE that cloned repo folder.
#   4. Each week, save your Canvas CSV export into that same folder too
#      (see CSV_PATH below).
BASE_DIR = Path(__file__).resolve().parent

# Path to the Canvas CSV you exported. Update this each week, OR just always
# save/rename your export to this exact filename before running the script.
# This is relative to BASE_DIR (the repo folder), so just drop the file in
# next to this script.
CSV_PATH = BASE_DIR / "grades.csv"

# Where to write the generated leaderboard HTML file. GitHub Pages will be
# configured to serve whatever is in this "docs" folder, so this ends up
# being your live kiosk page.
HTML_OUTPUT_PATH = BASE_DIR / "docs" / "index.html"

# The keyword used to find "completion check" columns in the CSV header.
# Any column whose header contains this text is treated as a homework
# check that counts toward the completion percentage.
COMPLETION_KEYWORD = "CYUP"

# The name of the CSV column that holds each student's class period.
SECTION_COLUMN = "Section"

# Optional: rename ugly Canvas section names to friendly display names.
# Key = exact text as it appears in the CSV "Section" column.
# Value = what you want displayed on the leaderboard.
# Any section NOT listed here will just be displayed using its raw CSV name.
SECTION_DISPLAY_NAMES = {
    "AP Precalculus 2-P02-Gribble": "Period 2",
    "AP Precalculus 2-P03-Gribble": "Period 3",
    "AP Precalculus 2-P04-Gribble": "Period 4",
    "AP Precalculus 2-P05-Gribble": "Period 5",
    "AP Precalculus 2-P06-Gribble": "Period 6",
}

# The title shown at the top of the leaderboard page.
PAGE_TITLE = "AP Precalculus 2 - Homework Completion Leaderboard"

# --- Git / GitHub Pages auto-publish settings ---

# Set this to True once you've tested the script and are ready to have it
# automatically commit + push. Leave False while you're testing so you don't
# accidentally push broken pages.
GIT_AUTO_PUSH = False

# The local folder that is a git repository connected to your GitHub Pages
# site (i.e. the folder you'd normally run `git add` / `git commit` in).
# This is just BASE_DIR again -- the folder this script lives in -- so it
# automatically points at the right place on any computer.
GIT_REPO_PATH = BASE_DIR

# The commit message used each time the script pushes an update.
GIT_COMMIT_MESSAGE = "Update homework completion leaderboard"


# =============================================================================
# LOGIC -- you shouldn't need to edit below here for normal use.
# =============================================================================


def load_gradebook_rows(csv_path):
    """
    Read the Canvas CSV and return a list of student rows as dictionaries
    (one dict per student, keys = column headers).

    Canvas always inserts a "Points Possible" summary row right after the
    header row -- that's not a real student, so we skip it.
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        sys.exit(
            f"ERROR: Could not find CSV file at '{csv_path}'. "
            f"Check the CSV_PATH setting at the top of the script."
        )

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    # Drop the "Points Possible" row. Canvas puts the text "Points Possible"
    # in the first column of that row instead of a student name.
    student_rows = [
        row for row in rows
        if not row.get("Student", "").strip().startswith("Points Possible")
    ]
    return student_rows


def find_completion_columns(fieldnames, keyword):
    """
    Return the list of column names that contain `keyword`.
    These are the "did the student complete this?" columns we'll grade.
    """
    matching_columns = [name for name in fieldnames if keyword in name]

    if not matching_columns:
        sys.exit(
            f"ERROR: No columns found containing '{keyword}'. "
            f"Check the COMPLETION_KEYWORD setting at the top of the script."
        )
    return matching_columns


def calculate_completion_by_section(student_rows, section_column, completion_columns):
    """
    For each section (class period), count how many of the completion
    columns are marked done ("1.00") versus how many were possible.

    Returns a dict like:
        {
            "AP Precalculus 2-P02-Gribble": {
                "completed": 159,
                "possible": 1312,
                "percentage": 12.12,
            },
            ...
        }
    """
    # completed/possible counters, one pair per section
    stats = {}

    for row in student_rows:
        section = row.get(section_column, "").strip()
        if not section:
            # Skip any row that has no section (shouldn't normally happen).
            continue

        if section not in stats:
            stats[section] = {"completed": 0, "possible": 0}

        for column in completion_columns:
            value = row.get(column, "").strip()
            stats[section]["possible"] += 1
            if value == "1.00":
                stats[section]["completed"] += 1

    # Now calculate a percentage for each section.
    for section, counts in stats.items():
        if counts["possible"] > 0:
            counts["percentage"] = round(
                counts["completed"] * 100 / counts["possible"], 2
            )
        else:
            counts["percentage"] = 0.0

    return stats


def apply_display_names(stats, display_names):
    """
    Swap raw Canvas section names for friendly display names where one is
    provided in SECTION_DISPLAY_NAMES. Sections without a mapping keep
    their original CSV name.
    """
    renamed_stats = {}
    for section, counts in stats.items():
        display_name = display_names.get(section, section)
        renamed_stats[display_name] = counts
    return renamed_stats


def generate_html(stats, page_title):
    """
    Build the leaderboard HTML page as a string, ranking sections from
    highest to lowest completion percentage.
    """
    # Sort sections by percentage, highest first.
    ranked_sections = sorted(
        stats.items(), key=lambda item: item[1]["percentage"], reverse=True
    )

    # Build one <li> row per section.
    row_html_pieces = []
    for rank, (section_name, counts) in enumerate(ranked_sections, start=1):
        row_html_pieces.append(
            f"""
            <li class="row">
                <span class="rank">#{rank}</span>
                <span class="name">{section_name}</span>
                <div class="bar-track">
                    <div class="bar-fill" style="width: {counts['percentage']}%;"></div>
                </div>
                <span class="percentage">{counts['percentage']}%</span>
            </li>
            """
        )
    rows_html = "\n".join(row_html_pieces)

    # The page auto-refreshes every 5 minutes (300 seconds) so the kiosk
    # Pi always shows the latest pushed version without anyone touching it.
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="300">
<title>{page_title}</title>
<style>
    body {{
        background: #0f172a;
        color: #f1f5f9;
        font-family: "Segoe UI", Arial, sans-serif;
        margin: 0;
        padding: 40px;
    }}
    h1 {{
        text-align: center;
        font-size: 2.5rem;
        margin-bottom: 40px;
    }}
    ul {{
        list-style: none;
        margin: 0 auto;
        padding: 0;
        max-width: 900px;
    }}
    .row {{
        display: flex;
        align-items: center;
        gap: 20px;
        padding: 18px 24px;
        margin-bottom: 14px;
        background: #1e293b;
        border-radius: 12px;
        font-size: 1.4rem;
    }}
    .rank {{
        width: 50px;
        font-weight: bold;
        color: #94a3b8;
    }}
    .name {{
        width: 220px;
        font-weight: 600;
    }}
    .bar-track {{
        flex-grow: 1;
        background: #334155;
        border-radius: 8px;
        overflow: hidden;
        height: 24px;
    }}
    .bar-fill {{
        height: 100%;
        background: linear-gradient(90deg, #22d3ee, #3b82f6);
    }}
    .percentage {{
        width: 80px;
        text-align: right;
        font-weight: bold;
    }}
</style>
</head>
<body>
    <h1>{page_title}</h1>
    <ul>
        {rows_html}
    </ul>
</body>
</html>
"""
    return html


def write_html_file(html, output_path):
    """Write the generated HTML string out to disk, creating folders if needed."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    print(f"Wrote leaderboard HTML to: {output_path}")


def git_commit_and_push(repo_path, commit_message):
    """
    Run the git commands needed to commit the updated HTML and push it to
    GitHub, so GitHub Pages picks up the new version automatically.

    Each git command is run one at a time so that if something goes wrong,
    you get a clear error message telling you which step failed.
    """
    commands = [
        ["git", "add", "-A"],
        ["git", "commit", "-m", commit_message],
        ["git", "push"],
    ]

    for command in commands:
        result = subprocess.run(
            command, cwd=repo_path, capture_output=True, text=True
        )
        print(f"$ {' '.join(command)}")
        if result.stdout.strip():
            print(result.stdout.strip())

        if result.returncode != 0:
            # "nothing to commit" is not really an error -- it just means
            # the leaderboard didn't change since last time. Keep going.
            if "nothing to commit" in result.stdout.lower():
                print("(No changes to commit -- leaderboard was already up to date.)")
                continue
            sys.exit(
                f"ERROR: git command failed: {' '.join(command)}\n{result.stderr.strip()}"
            )

    print("Successfully pushed updated leaderboard to GitHub.")


def main():
    print(f"Reading gradebook from: {CSV_PATH}")
    student_rows = load_gradebook_rows(CSV_PATH)
    print(f"Loaded {len(student_rows)} students.")

    fieldnames = student_rows[0].keys() if student_rows else []
    completion_columns = find_completion_columns(fieldnames, COMPLETION_KEYWORD)
    print(f"Found {len(completion_columns)} '{COMPLETION_KEYWORD}' columns to grade.")

    stats = calculate_completion_by_section(
        student_rows, SECTION_COLUMN, completion_columns
    )
    stats = apply_display_names(stats, SECTION_DISPLAY_NAMES)

    print("\nCompletion by section:")
    for section, counts in sorted(
        stats.items(), key=lambda item: item[1]["percentage"], reverse=True
    ):
        print(
            f"  {section}: {counts['percentage']}% "
            f"({counts['completed']}/{counts['possible']})"
        )

    html = generate_html(stats, PAGE_TITLE)
    write_html_file(html, HTML_OUTPUT_PATH)

    if GIT_AUTO_PUSH:
        git_commit_and_push(GIT_REPO_PATH, GIT_COMMIT_MESSAGE)
    else:
        print(
            "\nGIT_AUTO_PUSH is set to False, so nothing was pushed to GitHub. "
            "Set GIT_AUTO_PUSH = True at the top of the script once you're ready."
        )


if __name__ == "__main__":
    main()
