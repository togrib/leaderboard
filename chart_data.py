"""
chart_data.py

Combines TWO Canvas exports and works out, for each topic, the AVERAGE
mastery score of students who did the practice vs. students who didn't:

    traditional.csv      - the regular gradebook export (has the CYUP columns)
    learningmastery.csv  - the Learning Mastery Gradebook export (has the
                           1-4 mastery "result" for each learning outcome)

The two files are matched up student-by-student using the Canvas ID
(column "ID" in the traditional file, "Student ID" in the mastery file).
Row order doesn't matter, so there's no need to sort or copy/paste data
between files first.

The results are written to docs/chart-data.json, which chart.html reads.

HOW TO RUN:
    1. Put this file in the SAME folder as leaderboard.py
       (it borrows a few functions from it).
    2. Save your two exports next to it as traditional.csv and
       learningmastery.csv (or change the file names in CONFIG below).
    3. Run:  python chart_data.py

Other handy command:
    python chart_data.py --list-columns    (shows the column names in both files)

The "math" is just: add up the scores in a group, divide by how many
students are in the group. That's all a group average is.
"""

import csv
import json
import sys
from datetime import datetime
from pathlib import Path

# Reuse pieces we already wrote in leaderboard.py so we don't copy-paste them:
#   is_completed         - decides if a cell counts as "done" (1, 1.0, 1.00 all work)
#   git_commit_and_push  - commits and pushes to GitHub
#   IGNORED_STUDENT_NAMES - the "Test Student" filter list
from leaderboard import (
    BASE_DIR,
    GIT_AUTO_PUSH,
    GIT_REPO_PATH,
    IGNORED_STUDENT_NAMES,
    is_completed,
    git_commit_and_push,
)


# =============================================================================
# CONFIG -- edit these values to match your setup
# =============================================================================

# The two Canvas exports (saved in the same folder as this script).
TRADITIONAL_CSV_PATH = BASE_DIR / "traditional.csv"
MASTERY_CSV_PATH = BASE_DIR / "learningmastery.csv"

# The column in each file that holds the Canvas ID, used to match students up.
TRADITIONAL_ID_COLUMN = "ID"
MASTERY_ID_COLUMN = "Student ID"

# Where to write the data file that chart.html reads.
JSON_OUTPUT_PATH = BASE_DIR / "docs" / "chart-data.json"

GIT_COMMIT_MESSAGE = "Update practice vs. no-practice chart"

# One entry per topic (one pair of bars on the chart).
# To REMOVE a topic from the chart, delete its lines (or put a # in front).
#
#   label            - short name shown under the bars
#   name             - full topic name (not shown on the chart right now)
#   practice_columns - the START of the CYUP column name(s) in the traditional
#                      file. Only the beginning is needed, so you can leave
#                      off the number in parentheses at the end, which makes
#                      this still work if Canvas changes it.
#                      If you list more than one column, a student only counts
#                      as "did the practice" if they completed ALL of them.
#   mastery_columns  - the EXACT name(s) of the "result" column(s) in the
#                      mastery file. If you list more than one, each student's
#                      score is the AVERAGE of them.
TOPICS = [
    {"label": "1.1+1.2", "name": "Rates of Change",
     "practice_columns": ["CYUP - 1.1 + 1.2 - "],
     "mastery_columns": ["Unit 1A > 1.1 result", "Unit 1A > 1.2 result"]},

    {"label": "1.3", "name": "AROC of Lin. & Quad.",
     "practice_columns": ["CYUP - 1.3 - "],
     "mastery_columns": ["Unit 1A > 1.3 result"]},

    {"label": "1.4", "name": "Poly & Rates of Change",
     "practice_columns": ["CYUP - 1.4 - "],
     "mastery_columns": ["Unit 1A > 1.4 result"]},

    # Note: there is also a "CYUP - 1.5 - Division Supplement" column. It is
    # left out here on purpose. To require BOTH 1.5 CYUPs, change the line
    # below to: ["CYUP - 1.5 - Polynomial", "CYUP - 1.5 - Division"]
    {"label": "1.5", "name": "Poly & Complex Zeros",
     "practice_columns": ["CYUP - 1.5 - Polynomial"],
     "mastery_columns": ["Unit 1A > 1.5 result"]},

    {"label": "1.6", "name": "End Behavior (Poly)",
     "practice_columns": ["CYUP - 1.6 - "],
     "mastery_columns": ["Unit 1A > 1.6 result"]},

    {"label": "1.7", "name": "End Behavior (Rational)",
     "practice_columns": ["CYUP - 1.7 - "],
     "mastery_columns": ["Unit 1B > 1.7 result"]},

    {"label": "1.8", "name": "Rational & Zeros",
     "practice_columns": ["CYUP - 1.8 - "],
     "mastery_columns": ["Unit 1B > 1.8 result"]},

    # Note: Canvas spelled the outcome "1.ten" instead of "1.10" -- that is
    # why the column name below looks odd. It has to match Canvas exactly.
    {"label": "1.9+1.10", "name": "Vertical Asymptotes & Holes",
     "practice_columns": ["CYUP - 1.9+1.10 - "],
     "mastery_columns": ["Unit 1B > 1.9 result", "Unit 1B > 1.ten result"]},

    {"label": "1.11", "name": "Equivalent Representations",
     "practice_columns": ["CYUP - 1.11 - "],
     "mastery_columns": ["Unit 1B > 1.11 result"]},
]


# =============================================================================
# LOGIC -- you shouldn't need to edit below here for normal use.
# =============================================================================


def read_csv_file(path):
    """
    Read a CSV file. Returns two things: the list of column names, and the
    list of rows (each row is a dictionary: column name -> cell text).

    encoding="utf-8-sig" quietly removes an invisible character that Canvas
    puts at the very start of some exports (it would otherwise stick to the
    first column name and break it).
    """
    path = Path(path)
    if not path.exists():
        sys.exit(f"ERROR: Could not find '{path}'. Check the file names in CONFIG.")

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        return reader.fieldnames, rows


def load_traditional_rows(path):
    """
    Load the traditional gradebook, removing the two rows that aren't real
    students: the "Points Possible" row and the Canvas "Test Student".
    """
    fieldnames, rows = read_csv_file(path)
    student_rows = [
        row for row in rows
        if not row.get("Student", "").strip().startswith("Points Possible")
        and row.get("Student", "").strip() not in IGNORED_STUDENT_NAMES
    ]
    return fieldnames, student_rows


def match_students(traditional_rows, mastery_rows):
    """
    Pair up each student's traditional row with their mastery row using the
    Canvas ID. Returns a list of (traditional_row, mastery_row) pairs, plus
    counts of anyone who could not be matched so you can spot problems.
    """
    # Build a lookup: Canvas ID -> mastery row.
    # (Like a phone book: give it an ID, get back that student's row.)
    mastery_by_id = {}
    for row in mastery_rows:
        student_id = row.get(MASTERY_ID_COLUMN, "").strip()
        if student_id:
            mastery_by_id[student_id] = row

    pairs = []
    unmatched_traditional = 0
    for row in traditional_rows:
        student_id = row.get(TRADITIONAL_ID_COLUMN, "").strip()
        if student_id in mastery_by_id:
            pairs.append((row, mastery_by_id[student_id]))
        else:
            unmatched_traditional += 1

    unmatched_mastery = len(mastery_by_id) - len(pairs)
    return pairs, unmatched_traditional, unmatched_mastery


def find_column(fieldnames, starts_with):
    """
    Find the one column whose name starts with the given text.
    Stops with a clear message if there are zero matches or several.
    """
    matches = [name for name in fieldnames if name.startswith(starts_with)]
    if len(matches) != 1:
        sys.exit(
            f"ERROR: Expected exactly 1 column starting with '{starts_with}' "
            f"but found {len(matches)}: {matches}\n"
            f"Run 'python chart_data.py --list-columns' to see the real names."
        )
    return matches[0]


def to_number(value):
    """
    Turn a CSV cell (text) into a number. Returns None if the cell is empty
    or isn't a number, so we can skip it instead of crashing.
    """
    value = (value or "").strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def average(numbers):
    """The average of a list of numbers, or None if the list is empty."""
    if not numbers:
        return None
    return sum(numbers) / len(numbers)


def calculate_topic(pairs, topic, traditional_fields, mastery_fields):
    """
    Work out the two group averages for one topic.

    For each student:
      1. Get their mastery score(s). If they have none (blank), skip them.
         If there are two scores (like 1.1 and 1.2), average them.
      2. Check whether they completed the practice column(s).
      3. Put their score in the "practice" list or the "no practice" list.
    Then average each list.
    """
    # Work out the real column names once, before looping over students
    practice_columns = [find_column(traditional_fields, start)
                        for start in topic["practice_columns"]]
    for column in topic["mastery_columns"]:
        if column not in mastery_fields:
            sys.exit(
                f"ERROR: Topic {topic['label']}: column '{column}' was not found "
                f"in the mastery file.\nRun 'python chart_data.py --list-columns'."
            )

    practice_scores = []
    no_practice_scores = []

    for traditional_row, mastery_row in pairs:
        scores = [to_number(mastery_row.get(column, ""))
                  for column in topic["mastery_columns"]]
        scores = [s for s in scores if s is not None]   # drop blanks
        student_score = average(scores)
        if student_score is None:
            continue   # no score for this topic, so leave them out

        # all(...) is True only if EVERY practice column is completed
        did_practice = all(
            is_completed(traditional_row.get(column, "")) for column in practice_columns
        )

        if did_practice:
            practice_scores.append(student_score)
        else:
            no_practice_scores.append(student_score)

    practice_mean = average(practice_scores)
    no_practice_mean = average(no_practice_scores)

    # The unit comes from the mastery column name, with no setup needed:
    # "Unit 1B > 1.7 result" -> "Unit 1B". chart.html shows one unit per page.
    unit = topic["mastery_columns"][0].split(" > ")[0]

    return {
        "label": topic["label"],
        "name": topic["name"],
        "unit": unit,
        # round to 4 decimal places; None becomes null in the JSON file
        "practice_mean": None if practice_mean is None else round(practice_mean, 4),
        "no_practice_mean": None if no_practice_mean is None else round(no_practice_mean, 4),
        "n_practice": len(practice_scores),
        "n_no_practice": len(no_practice_scores),
    }


def write_json_file(topic_results, output_path):
    """Write the results out as a JSON file that chart.html can read."""
    now = datetime.now()
    data = {
        "updated": f"{now.month}/{now.day}/{now.year}",
        "topics": topic_results,
    }
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Wrote chart data to: {output_path}")


def main():
    traditional_fields, traditional_rows = load_traditional_rows(TRADITIONAL_CSV_PATH)
    mastery_fields, mastery_rows = read_csv_file(MASTERY_CSV_PATH)

    # "--list-columns" just prints the column names from both files and stops
    if "--list-columns" in sys.argv:
        print("TRADITIONAL file columns:")
        for name in traditional_fields:
            print(f"  {name}")
        print("\nMASTERY file columns:")
        for name in mastery_fields:
            print(f"  {name}")
        return

    pairs, unmatched_traditional, unmatched_mastery = match_students(
        traditional_rows, mastery_rows
    )
    print(f"Matched {len(pairs)} students across the two files.")
    print(f"  Traditional rows with no mastery match: {unmatched_traditional}")
    print(f"  Mastery rows with no traditional match: {unmatched_mastery} "
          f"(1 is normal: the Canvas Test Student)")

    topic_results = [
        calculate_topic(pairs, topic, traditional_fields, mastery_fields)
        for topic in TOPICS
    ]

    # Print a quick summary so you can sanity-check the numbers
    print("\nGroup averages (no practice / practice):")
    for result in topic_results:
        print(
            f"  {result['label']:>8}: "
            f"{result['no_practice_mean']} (n={result['n_no_practice']})  /  "
            f"{result['practice_mean']} (n={result['n_practice']})"
        )

    write_json_file(topic_results, JSON_OUTPUT_PATH)

    if GIT_AUTO_PUSH:
        git_commit_and_push(GIT_REPO_PATH, GIT_COMMIT_MESSAGE)
    else:
        print("\nGIT_AUTO_PUSH is False, so nothing was pushed to GitHub.")


if __name__ == "__main__":
    main()
