import csv
import sys
import tempfile
import unittest
import io
import contextlib
from datetime import datetime
from pathlib import Path
from unittest import mock
import os
from zoneinfo import ZoneInfo

import yaml

import codepath_to_canvas


CODEPATH_HEADER = [
  "First Name",
  "Last Name",
  "Github Username",
  "Hours Spent",
  "Submitted",
  "Updated",
  "Feature Score",
  "Status",
  "Assigned Grader",
  "Graded At",
  "Submission URL",
  "Notes",
]

CANVAS_HEADER = [
  "Student",
  "ID",
  "SIS User ID",
  "SIS Login ID",
  "Section",
  "Project 3 (575121)",
]


class CodePathToCanvasTests(unittest.TestCase):
  def test_convert_feature_score_uses_base_and_weighted_stretch(self) -> None:
    config = codepath_to_canvas.ScoreConfig(
      base_points=10,
      stretch_points=10,
      ignore_points=2,
      stretch_weight=0.5,
      raw_output_points=14,
      canvas_value=70,
      canvas_scale=5,
      effective_base_points=10,
      effective_stretch_points=8,
      effective_total_points=18,
    )

    self.assertEqual(codepath_to_canvas.convert_feature_score(14, config), 60)
    self.assertEqual(codepath_to_canvas.convert_feature_score(40, config), 70)

  def test_resolve_name_matches_uses_exact_tokens_and_existing_map(self) -> None:
    confirmed, suggested, unresolved, warnings = codepath_to_canvas.resolve_name_matches(
      codepath_names=[
        "Joceline Cortez-Arellano",
        "Sam Jacobs",
        "Missing Student",
      ],
      canvas_names=[
        "Arellano, Joceline Cortez",
        "Jacobs, Samuel",
      ],
      existing_map={"Sam Jacobs": "Jacobs, Samuel"},
      auto_match_threshold=100,
      auto_match_gap=4,
      suggestion_count=3,
    )

    self.assertEqual(confirmed["Joceline Cortez-Arellano"], "Arellano, Joceline Cortez")
    self.assertEqual(confirmed["Sam Jacobs"], "Jacobs, Samuel")
    self.assertEqual(suggested, {})
    self.assertIn("Missing Student", unresolved)
    self.assertEqual(warnings, [])

  def test_compute_seconds_late_defaults_to_submitted_timestamp(self) -> None:
    submitted_at, seconds_late = codepath_to_canvas.compute_seconds_late(
      {
        "Submitted": "3/10 at 12:30pm PDT",
        "Updated": "3/10 at 1:30pm PDT",
      },
      due_at=datetime(2026, 3, 10, 12, 0, tzinfo=ZoneInfo("America/Los_Angeles")),
    )

    self.assertIsNotNone(submitted_at)
    self.assertEqual(
      submitted_at,
      datetime(2026, 3, 10, 12, 30, tzinfo=ZoneInfo("America/Los_Angeles")),
    )
    self.assertEqual(seconds_late, 1800)

  def test_compute_seconds_late_uses_updated_timestamp_in_strict_mode(self) -> None:
    submitted_at, seconds_late = codepath_to_canvas.compute_seconds_late(
      {
        "Submitted": "3/10 at 12:30pm PDT",
        "Updated": "3/10 at 1:30pm PDT",
      },
      due_at=datetime(2026, 3, 10, 12, 0, tzinfo=ZoneInfo("America/Los_Angeles")),
      strict_deadlines=True,
    )

    self.assertIsNotNone(submitted_at)
    self.assertEqual(
      submitted_at,
      datetime(2026, 3, 10, 13, 30, tzinfo=ZoneInfo("America/Los_Angeles")),
    )
    self.assertEqual(seconds_late, 5400)

  def test_compute_seconds_late_requires_submitted_timestamp(self) -> None:
    submitted_at, seconds_late = codepath_to_canvas.compute_seconds_late(
      {
        "Submitted": "",
        "Updated": "3/10 at 1:30pm PDT",
      },
      due_at=datetime(2026, 3, 10, 12, 0, tzinfo=ZoneInfo("America/Los_Angeles")),
      strict_deadlines=True,
    )

    self.assertIsNone(submitted_at)
    self.assertIsNone(seconds_late)

  def test_save_name_map_marks_suggestions_separately(self) -> None:
    with tempfile.TemporaryDirectory() as tempdir:
      name_map = Path(tempdir) / "name_map.yaml"
      codepath_to_canvas.save_name_map(
        name_map,
        confirmed_mapping={"Sam Jacobs": "Jacobs, Samuel"},
        suggested_mapping={"Jon Smyth": "Smith, John"},
        unmatched=["Mystery Student"],
      )

      written_map = yaml.safe_load(name_map.read_text(encoding="utf-8"))
      self.assertEqual(written_map["CONFIRMED"]["Jacobs, Samuel"], ["Sam Jacobs"])
      self.assertEqual(written_map["SUGGESTED"]["Smith, John"], ["Jon Smyth"])
      self.assertEqual(written_map["UNMATCHED"], ["Mystery Student"])

  def test_load_gradebook_assignment_rows_does_not_require_max_row(self) -> None:
    class FakeWorksheet:
      def iter_rows(self, values_only: bool = False):
        self.called_with_values_only = values_only
        header = (
          "Member ID",
          "Github",
          "Status",
          "Full Name",
          "Feature Score",
          "Extra Col 1",
          "Extra Col 2",
          "Submitted",
          "Updated",
        )
        student = (
          146762,
          "abplas",
          "Complete",
          "Abel Plascencia",
          "10",
          None,
          None,
          "2/16 at 12:55am PST",
          "---",
        )
        return iter([
          ("ASN - 1 GRADEBOOK", None, None, None, None),
          ("Coursework Type", "ASN", None, None, None),
          ("Unit", 1, None, None, None),
          ("Deadline", None, None, None, None),
          (None, None, None, None, None),
          ("OK", None, "Required Score", 10, None),
          header,
          student,
          (None, None, None, None, None),
        ])

    class FakeWorkbook:
      sheetnames = ["ASN - 1"]

      def __getitem__(self, name: str):
        self.worksheet = FakeWorksheet()
        return self.worksheet

      def close(self):
        return None

    fake_workbook = FakeWorkbook()
    fake_openpyxl = mock.Mock()
    fake_openpyxl.load_workbook.return_value = fake_workbook

    with mock.patch.dict(sys.modules, {"openpyxl": fake_openpyxl}):
      rows, skip_message = codepath_to_canvas.load_gradebook_assignment_rows(
        Path("Gradebook.xlsx"),
        "ASN - 1",
      )

    self.assertIsNone(skip_message)
    self.assertEqual(rows[0]["Member ID"], "146762")
    self.assertEqual(rows[0]["Feature Score"], "10")
    self.assertEqual(rows[0]["Submitted"], "2/16 at 12:55am PST")

  def test_push_preflight_warns_about_unmatched_canvas_roster_students(self) -> None:
    args = mock.Mock()
    args.base_points = 10.0
    args.stretch_points = 0.0
    args.ignore_points = 0.0
    args.stretch_weight = 0.5
    args.canvas_value = None
    args.name_map = "missing_name_map.yaml"
    args.write_suggestions = None
    args.auto_match_threshold = 100
    args.auto_match_gap = 4
    args.suggestion_count = 3
    args.prompt_for_matches = False
    args.verbose = False
    args.strict_deadlines = False
    args.missing_as_zero = False
    args.leave_not_graded_blank = False

    class FakeAssignment:
      id = 123
      name = "ASN - 1"
      points_possible = 100

    stderr = io.StringIO()
    stdout = io.StringIO()
    with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(stdout):
      exit_code = codepath_to_canvas.run_single_push_conversion(
        args=args,
        codepath_path=None,
        roster_rows=[
          {"Student": "Alpha, Alice", "ID": "1"},
          {"Student": "Beta, Bob", "ID": "2"},
        ],
        canvas_assignment=FakeAssignment(),
        assignment_name="ASN - 1",
        codepath_rows=[
          {
            "First Name": "Alice",
            "Last Name": "Alpha",
            "Feature Score": "10",
            "Status": "Complete",
            "Submitted": "3/10 at 12:00pm PDT",
            "Updated": "3/10 at 12:00pm PDT",
          },
        ],
        push_enabled=False,
      )

    self.assertEqual(exit_code, 0)
    self.assertIn("Canvas roster student(s) have no CodePath match", stderr.getvalue())
    self.assertIn("Beta, Bob", stderr.getvalue())

  def test_load_gradebook_assignment_rows_handles_duplicate_headers_and_score_column(self) -> None:
    class FakeWorksheet:
      def iter_rows(self, values_only: bool = False):
        self.called_with_values_only = values_only
        header = (
          "Member ID",
          "Github",
          "Status",
          "Full Name",
          "Feature Score",
          "Feature Score %",
          "Updated Score?",
          "Repo URL",
          "Submission Report",
          "Group",
          "First Name",
          "Last Name",
          "Github Handle",
          "Submitted",
          "Updated",
          "Score",
          "Status",
          "Submission URL",
          "Notes",
          "",
          "",
          "Member ID",
          "Github",
          "Status",
          "Full Name",
          "Feature Score",
        )
        student = (
          999,
          "octocat",
          "Complete",
          "Octo Cat",
          "",
          "100%",
          "",
          "",
          "",
          "G1",
          "Octo",
          "Cat",
          "octocat",
          "3/10 at 12:00pm PDT",
          "3/10 at 12:05pm PDT",
          "17",
          "Complete",
          "",
          "",
          "",
          "",
          "",
          "",
          "",
          "",
          "",
        )
        return iter([
          ("GM - 8 GRADEBOOK", None),
          header,
          student,
        ])

    class FakeWorkbook:
      sheetnames = ["GM - 8"]

      def __getitem__(self, name: str):
        self.worksheet = FakeWorksheet()
        return self.worksheet

      def close(self):
        return None

    fake_workbook = FakeWorkbook()
    fake_openpyxl = mock.Mock()
    fake_openpyxl.load_workbook.return_value = fake_workbook

    with mock.patch.dict(sys.modules, {"openpyxl": fake_openpyxl}):
      rows, skip_message = codepath_to_canvas.load_gradebook_assignment_rows(
        Path("Gradebook.xlsx"),
        "GM - 8",
      )

    self.assertIsNone(skip_message)
    self.assertEqual(len(rows), 1)
    self.assertEqual(rows[0]["Member ID"], "999")
    self.assertEqual(rows[0]["Full Name"], "Octo Cat")
    self.assertEqual(rows[0]["Feature Score"], "17")
    self.assertEqual(rows[0]["Submitted"], "3/10 at 12:00pm PDT")

  def test_push_clears_late_override_when_seconds_late_is_zero(self) -> None:
    args = mock.Mock()
    args.base_points = 10.0
    args.stretch_points = 0.0
    args.ignore_points = 0.0
    args.stretch_weight = 0.5
    args.canvas_value = None
    args.name_map = "missing_name_map.yaml"
    args.write_suggestions = None
    args.auto_match_threshold = 100
    args.auto_match_gap = 4
    args.suggestion_count = 3
    args.prompt_for_matches = False
    args.verbose = False
    args.strict_deadlines = False
    args.missing_as_zero = False
    args.leave_not_graded_blank = False

    class FakeSubmission:
      def __init__(self):
        self.edits: list[dict[str, object]] = []
        self.submitted_at = "2026-03-10T11:00:00-07:00"
        self.submission_type = "online_upload"
        self.excused = False
        self.attachments = []
        self.body = ""
        self.url = ""
        self.media_comment_id = None

      def edit(self, **kwargs):
        self.edits.append(kwargs)
        return True

    class FakeAssignment:
      id = 123
      name = "unit7"
      points_possible = 100
      due_at = datetime(2026, 3, 10, 12, 0, tzinfo=ZoneInfo("America/Los_Angeles"))

      def __init__(self):
        self.pushes: list[dict[str, object]] = []
        self.submission = FakeSubmission()

      def get_submission(self, user_id: int):
        return self.submission

      def push_feedback(self, *, user_id, score: float, comments: str, seconds_late: int | None = None, **kwargs):
        self.pushes.append({"user_id": user_id, "score": score, "comments": comments, "seconds_late": seconds_late})
        return True

    assignment = FakeAssignment()
    exit_code = codepath_to_canvas.run_single_push_conversion(
      args=args,
      codepath_path=None,
      roster_rows=[{"Student": "Alpha, Alice", "ID": "1"}],
      canvas_assignment=assignment,
      assignment_name="unit7",
      codepath_rows=[
        {
          "First Name": "Alice",
          "Last Name": "Alpha",
          "Feature Score": "10",
          "Status": "Complete",
          "Submitted": "3/10 at 11:59am PDT",
          "Updated": "3/10 at 12:59pm PDT",
        }
      ],
      push_enabled=True,
    )

    self.assertEqual(exit_code, 0)
    self.assertEqual(assignment.pushes[0]["seconds_late"], 0)
    self.assertIn(
      {"submission": {"late_policy_status": "none", "seconds_late_override": 0}},
      assignment.submission.edits,
    )

  def test_main_writes_canvas_csv_and_name_map(self) -> None:
    with tempfile.TemporaryDirectory() as tempdir:
      root = Path(tempdir)
      codepath_csv = root / "codepath.csv"
      canvas_csv = root / "canvas.csv"
      name_map = root / "name_map.yaml"

      self.write_codepath_csv(
        codepath_csv,
        [
          {
            "First Name": "Joceline",
            "Last Name": "Cortez-Arellano",
            "Github Username": "jc",
            "Hours Spent": "1",
            "Submitted": "",
            "Updated": "",
            "Feature Score": "14",
            "Status": "Complete",
            "Assigned Grader": "",
            "Graded At": "",
            "Submission URL": "",
            "Notes": "",
          },
          {
            "First Name": "Jackie",
            "Last Name": "Luc",
            "Github Username": "jl",
            "Hours Spent": "1",
            "Submitted": "",
            "Updated": "",
            "Feature Score": "13",
            "Status": "Not Graded",
            "Assigned Grader": "",
            "Graded At": "",
            "Submission URL": "",
            "Notes": "",
          },
          {
            "First Name": "Sam",
            "Last Name": "Jacobs",
            "Github Username": "sj",
            "Hours Spent": "1",
            "Submitted": "",
            "Updated": "",
            "Feature Score": "",
            "Status": "Complete",
            "Assigned Grader": "",
            "Graded At": "",
            "Submission URL": "",
            "Notes": "",
          },
        ],
      )
      self.write_canvas_csv(
        canvas_csv,
        [
          ["    Points Possible", "", "", "", "", "100"],
          ["Arellano, Joceline Cortez", "1", "u1", "u1", "sec", ""],
          ["Luc, Jackie", "2", "u2", "u2", "sec", ""],
          ["Jacobs, Samuel", "3", "u3", "u3", "sec", ""],
        ],
      )
      name_map.write_text(
        yaml.safe_dump({"CONFIRMED": {"Jacobs, Samuel": ["Sam Jacobs"]}}),
        encoding="utf-8",
      )

      exit_code = codepath_to_canvas.main(
        [
          "--in",
          str(codepath_csv),
          "--canvas",
          str(canvas_csv),
          "--name-map",
          str(name_map),
          "--base-points",
          "10",
          "--stretch-points",
          "10",
          "--stretch-weight",
          "0.5",
          "--canvas-value",
          "100",
        ]
      )

      self.assertEqual(exit_code, 0)

      with canvas_csv.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

      self.assertEqual(rows[0]["Project 3 (575121)"], "100")
      self.assertEqual(rows[1]["Project 3 (575121)"], "80")
      self.assertEqual(rows[2]["Project 3 (575121)"], "0")
      self.assertEqual(rows[3]["Project 3 (575121)"], "")

      written_map = yaml.safe_load(name_map.read_text(encoding="utf-8"))
      self.assertEqual(written_map["CONFIRMED"]["Jacobs, Samuel"], ["Sam Jacobs"])
      self.assertEqual(
        written_map["CONFIRMED"]["Arellano, Joceline Cortez"],
        ["Joceline Cortez-Arellano"],
      )
      self.assertNotIn("SUGGESTED", written_map)

  def test_main_fails_when_only_fuzzy_suggestion_exists(self) -> None:
    with tempfile.TemporaryDirectory() as tempdir:
      root = Path(tempdir)
      codepath_csv = root / "codepath.csv"
      canvas_csv = root / "canvas.csv"
      name_map = root / "name_map.yaml"

      self.write_codepath_csv(
        codepath_csv,
        [
          {
            "First Name": "Sam",
            "Last Name": "Jacobs",
            "Github Username": "sj",
            "Hours Spent": "1",
            "Submitted": "",
            "Updated": "",
            "Feature Score": "14",
            "Status": "Complete",
            "Assigned Grader": "",
            "Graded At": "",
            "Submission URL": "",
            "Notes": "",
          },
        ],
      )
      self.write_canvas_csv(
        canvas_csv,
        [
          ["    Points Possible", "", "", "", "", "100"],
          ["Jacobs, Samuel", "3", "u3", "u3", "sec", ""],
        ],
      )

      name_map.write_text(
        yaml.safe_dump({"CONFIRMED": {"Sam Jacobs": ["Sam Jacobs"]}}),
        encoding="utf-8",
      )

      exit_code = codepath_to_canvas.main(
        [
          "--in",
          str(codepath_csv),
          "--canvas",
          str(canvas_csv),
          "--name-map",
          str(name_map),
          "--base-points",
          "10",
          "--stretch-points",
          "10",
          "--stretch-weight",
          "0.5",
          "--canvas-value",
          "100",
        ]
      )

      self.assertEqual(exit_code, 1)

      with canvas_csv.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

      self.assertEqual(rows[0]["Project 3 (575121)"], "100")
      self.assertEqual(rows[1]["Project 3 (575121)"], "")

      written_map = yaml.safe_load(name_map.read_text(encoding="utf-8"))
      self.assertEqual(written_map["SUGGESTED"]["Jacobs, Samuel"], ["Sam Jacobs"])
      self.assertNotIn("Sam Jacobs", written_map.get("CONFIRMED", {}))

  def test_batch_mode_uses_assignments_yaml(self) -> None:
    with tempfile.TemporaryDirectory() as tempdir:
      root = Path(tempdir)
      assignments_yaml = root / "assignments.yaml"
      name_map = root / "name_map.yaml"
      codepath_csv = root / "codepath-unit1.csv"
      canvas_csv = root / "canvas-unit1.csv"

      assignments_yaml.write_text(
        yaml.safe_dump(
          {
            "unit1": {
              "base": 10,
              "stretch": 10,
              "ignore": 0,
            }
          }
        ),
        encoding="utf-8",
      )
      name_map.write_text(
        yaml.safe_dump({"CONFIRMED": {"Jacobs, Samuel": ["Sam Jacobs"]}}),
        encoding="utf-8",
      )
      self.write_codepath_csv(
        codepath_csv,
        [
          {
            "First Name": "Sam",
            "Last Name": "Jacobs",
            "Github Username": "sj",
            "Hours Spent": "1",
            "Submitted": "",
            "Updated": "",
            "Feature Score": "14",
            "Status": "Complete",
            "Assigned Grader": "",
            "Graded At": "",
            "Submission URL": "",
            "Notes": "",
          },
        ],
      )
      self.write_canvas_csv(
        canvas_csv,
        [
          ["    Points Possible", "", "", "", "", "100"],
          ["Jacobs, Samuel", "3", "u3", "u3", "sec", ""],
        ],
      )

      exit_code = codepath_to_canvas.main(
        [
          "--assignments",
          str(assignments_yaml),
          "--data-dir",
          str(root),
          "--name-map",
          str(name_map),
          "--stretch-weight",
          "0.5",
        ]
      )

      self.assertEqual(exit_code, 0)
      with canvas_csv.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

      self.assertEqual(rows[1]["Project 3 (575121)"], "80")

  def test_batch_mode_skips_future_roster_only_codepath_export(self) -> None:
    with tempfile.TemporaryDirectory() as tempdir:
      root = Path(tempdir)
      assignments_yaml = root / "assignments.yaml"
      name_map = root / "name_map.yaml"
      codepath_csv = root / "codepath-unit6.csv"
      canvas_csv = root / "canvas-unit6.csv"

      assignments_yaml.write_text(
        yaml.safe_dump(
          {
            "unit6": {
              "base": 10,
              "stretch": 5,
              "ignore": 0,
            }
          }
        ),
        encoding="utf-8",
      )
      name_map.write_text("", encoding="utf-8")
      codepath_csv.write_text("Full Name\nSam Jacobs\n", encoding="utf-8")
      self.write_canvas_csv(
        canvas_csv,
        [
          ["    Points Possible", "", "", "", "", "100"],
          ["Jacobs, Samuel", "3", "u3", "u3", "sec", ""],
        ],
      )

      exit_code = codepath_to_canvas.main(
        [
          "--assignments",
          str(assignments_yaml),
          "--data-dir",
          str(root),
          "--name-map",
          str(name_map),
          "--stretch-weight",
          "0.5",
        ]
      )

      self.assertEqual(exit_code, 0)
      with canvas_csv.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

      self.assertEqual(rows[1]["Project 3 (575121)"], "")

  def test_batch_push_uses_canvas_roster_from_api(self) -> None:
    class FakeStudent:
      def __init__(self, name: str, user_id: int):
        self.name = name
        self.user_id = user_id

    class FakeSubmission:
      def __init__(self):
        self.submitted_at = "2026-03-10T12:00:00-07:00"
        self.submission_type = "online_upload"
        self.excused = False
        self.attachments = []
        self.body = ""
        self.url = ""
        self.media_comment_id = None

      def edit(self, **kwargs):
        return True

    class FakeAssignment:
      def __init__(self):
        self.id = 575119
        self.name = "Project 1"
        self.points_possible = 100
        self.due_at = datetime(2026, 3, 10, 12, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
        self.pushes: list[dict[str, object]] = []
        self.submission = FakeSubmission()

      def push_feedback(self, **kwargs):
        self.pushes.append(kwargs)
        return True

      def get_submission(self, user_id: int):
        return self.submission

    class FakeCourse:
      def __init__(self):
        self.assignment = FakeAssignment()

      def get_students(self, include_names: bool = False):
        return [FakeStudent("Jacobs, Samuel", 3)]

      def get_assignment(self, assignment_id: int):
        self.assignment.id = assignment_id
        return self.assignment

    class FakeCanvasInterface:
      last_instance = None

      def __init__(self, *args, **kwargs):
        self.kwargs = kwargs
        self.course = FakeCourse()
        FakeCanvasInterface.last_instance = self

      def get_course(self, course_id: int):
        self.course.course_id = course_id
        return self.course

    with tempfile.TemporaryDirectory() as tempdir:
      root = Path(tempdir)
      assignments_yaml = root / "assignments.yaml"
      name_map = root / "name_map.yaml"
      codepath_csv = root / "codepath-unit1.csv"

      assignments_yaml.write_text(
        yaml.safe_dump(
          {
            "course-id": 32639,
            "unit1": {
              "assignment-id": 575119,
              "base": 10,
              "stretch": 10,
              "ignore": 0,
            }
          }
        ),
        encoding="utf-8",
      )
      name_map.write_text(
        yaml.safe_dump({"CONFIRMED": {"Jacobs, Samuel": ["Sam Jacobs"]}}),
        encoding="utf-8",
      )
      self.write_codepath_csv(
        codepath_csv,
        [
          {
            "First Name": "Sam",
            "Last Name": "Jacobs",
            "Github Username": "sj",
            "Hours Spent": "1",
            "Submitted": "3/10 at 12:30pm PDT",
            "Updated": "",
            "Feature Score": "14",
            "Status": "Complete",
            "Assigned Grader": "",
            "Graded At": "",
            "Submission URL": "",
            "Notes": "",
          },
        ],
      )

      with mock.patch.object(codepath_to_canvas, "CanvasInterface", FakeCanvasInterface):
        exit_code = codepath_to_canvas.main(
          [
            "--assignments",
            str(assignments_yaml),
            "--data-dir",
            str(root),
            "--name-map",
            str(name_map),
            "--stretch-weight",
            "0.5",
          ]
        )

      self.assertEqual(exit_code, 0)
      fake_interface = FakeCanvasInterface.last_instance
      self.assertIsNotNone(fake_interface)
      self.assertEqual(fake_interface.kwargs["prod"], False)
      self.assertEqual(fake_interface.kwargs["privacy_mode"], "none")
      self.assertEqual(fake_interface.course.assignment.pushes[0]["user_id"], 3)
      self.assertEqual(fake_interface.course.assignment.pushes[0]["score"], 80)
      self.assertEqual(fake_interface.course.assignment.pushes[0]["seconds_late"], 1800)
      self.assertIn("Base points:", fake_interface.course.assignment.pushes[0]["comments"])
      self.assertIn("Stretch points:", fake_interface.course.assignment.pushes[0]["comments"])

  def test_batch_push_uses_updated_timestamp_when_strict_deadlines_enabled(self) -> None:
    class FakeStudent:
      def __init__(self, name: str, user_id: int):
        self.name = name
        self.user_id = user_id

    class FakeSubmission:
      def __init__(self):
        self.submitted_at = "2026-03-10T12:00:00-07:00"
        self.submission_type = "online_upload"
        self.excused = False
        self.attachments = []
        self.body = ""
        self.url = ""
        self.media_comment_id = None

      def edit(self, **kwargs):
        return True

    class FakeAssignment:
      def __init__(self):
        self.id = 575119
        self.name = "Project 1"
        self.points_possible = 100
        self.due_at = datetime(2026, 3, 10, 12, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
        self.pushes: list[dict[str, object]] = []
        self.submission = FakeSubmission()

      def push_feedback(self, **kwargs):
        self.pushes.append(kwargs)
        return True

      def get_submission(self, user_id: int):
        return self.submission

    class FakeCourse:
      def __init__(self):
        self.assignment = FakeAssignment()

      def get_students(self, include_names: bool = False):
        return [FakeStudent("Jacobs, Samuel", 3)]

      def get_assignment(self, assignment_id: int):
        self.assignment.id = assignment_id
        return self.assignment

    class FakeCanvasInterface:
      last_instance = None

      def __init__(self, *args, **kwargs):
        self.kwargs = kwargs
        self.course = FakeCourse()
        FakeCanvasInterface.last_instance = self

      def get_course(self, course_id: int):
        self.course.course_id = course_id
        return self.course

    with tempfile.TemporaryDirectory() as tempdir:
      root = Path(tempdir)
      assignments_yaml = root / "assignments.yaml"
      name_map = root / "name_map.yaml"
      codepath_csv = root / "codepath-unit1.csv"

      assignments_yaml.write_text(
        yaml.safe_dump(
          {
            "course-id": 32639,
            "unit1": {
              "assignment-id": 575119,
              "base": 10,
              "stretch": 10,
              "ignore": 0,
            }
          }
        ),
        encoding="utf-8",
      )
      name_map.write_text(
        yaml.safe_dump({"CONFIRMED": {"Jacobs, Samuel": ["Sam Jacobs"]}}),
        encoding="utf-8",
      )
      self.write_codepath_csv(
        codepath_csv,
        [
          {
            "First Name": "Sam",
            "Last Name": "Jacobs",
            "Github Username": "sj",
            "Hours Spent": "1",
            "Submitted": "3/10 at 12:30pm PDT",
            "Updated": "3/10 at 1:30pm PDT",
            "Feature Score": "14",
            "Status": "Complete",
            "Assigned Grader": "",
            "Graded At": "",
            "Submission URL": "",
            "Notes": "",
          },
        ],
      )

      with mock.patch.object(codepath_to_canvas, "CanvasInterface", FakeCanvasInterface):
        exit_code = codepath_to_canvas.main(
          [
            "--assignments",
            str(assignments_yaml),
            "--data-dir",
            str(root),
            "--name-map",
            str(name_map),
            "--strict-deadlines",
          ]
        )

      self.assertEqual(exit_code, 0)
      fake_interface = FakeCanvasInterface.last_instance
      self.assertIsNotNone(fake_interface)
      self.assertEqual(fake_interface.course.assignment.pushes[0]["seconds_late"], 5400)
      self.assertIn(
        "CodePath deadline timestamp used: 2026-03-10T13:30:00-07:00",
        fake_interface.course.assignment.pushes[0]["comments"],
      )

  def test_batch_push_marks_submission_missing_when_submitted_timestamp_is_absent(self) -> None:
    class FakeStudent:
      def __init__(self, name: str, user_id: int):
        self.name = name
        self.user_id = user_id

    class FakeSubmission:
      def __init__(self):
        self.edit_calls: list[dict[str, object]] = []

      def edit(self, **kwargs):
        self.edit_calls.append(kwargs)
        return True

    class FakeAssignment:
      def __init__(self):
        self.id = 575119
        self.name = "Project 1"
        self.points_possible = 100
        self.due_at = datetime(2026, 3, 1, 12, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
        self.pushes: list[dict[str, object]] = []
        self.submission = FakeSubmission()

      def push_feedback(self, **kwargs):
        self.pushes.append(kwargs)
        return True

      def get_submission(self, user_id: int):
        return self.submission

    class FakeCourse:
      def __init__(self):
        self.assignment = FakeAssignment()

      def get_students(self, include_names: bool = False):
        return [FakeStudent("Jacobs, Samuel", 3)]

      def get_assignment(self, assignment_id: int):
        self.assignment.id = assignment_id
        return self.assignment

    class FakeCanvasInterface:
      last_instance = None

      def __init__(self, *args, **kwargs):
        self.kwargs = kwargs
        self.course = FakeCourse()
        FakeCanvasInterface.last_instance = self

      def get_course(self, course_id: int):
        self.course.course_id = course_id
        return self.course

    with tempfile.TemporaryDirectory() as tempdir:
      root = Path(tempdir)
      assignments_yaml = root / "assignments.yaml"
      name_map = root / "name_map.yaml"
      codepath_csv = root / "codepath-unit1.csv"

      assignments_yaml.write_text(
        yaml.safe_dump(
          {
            "course-id": 32639,
            "unit1": {
              "assignment-id": 575119,
              "base": 10,
              "stretch": 10,
              "ignore": 0,
            }
          }
        ),
        encoding="utf-8",
      )
      name_map.write_text(
        yaml.safe_dump({"CONFIRMED": {"Jacobs, Samuel": ["Sam Jacobs"]}}),
        encoding="utf-8",
      )
      self.write_codepath_csv(
        codepath_csv,
        [
          {
            "First Name": "Sam",
            "Last Name": "Jacobs",
            "Github Username": "sj",
            "Hours Spent": "1",
            "Submitted": "",
            "Updated": "3/10 at 1:30pm PDT",
            "Feature Score": "14",
            "Status": "Complete",
            "Assigned Grader": "",
            "Graded At": "",
            "Submission URL": "",
            "Notes": "",
          },
        ],
      )

      with mock.patch.object(codepath_to_canvas, "CanvasInterface", FakeCanvasInterface):
        exit_code = codepath_to_canvas.main(
          [
            "--assignments",
            str(assignments_yaml),
            "--data-dir",
            str(root),
            "--name-map",
            str(name_map),
            "--strict-deadlines",
          ]
        )

      self.assertEqual(exit_code, 0)
      fake_interface = FakeCanvasInterface.last_instance
      self.assertIsNotNone(fake_interface)
      self.assertEqual(fake_interface.course.assignment.pushes, [])
      self.assertEqual(
        fake_interface.course.assignment.submission.edit_calls,
        [{"submission": {"late_policy_status": "missing"}}],
      )

  def test_batch_push_marks_canvas_only_student_missing_after_due_date(self) -> None:
    class FakeStudent:
      def __init__(self, name: str, user_id: int):
        self.name = name
        self.user_id = user_id

    class FakeSubmission:
      def __init__(self, *, submitted_at=None, submission_type="none", excused=False):
        self.submitted_at = submitted_at
        self.submission_type = submission_type
        self.excused = excused
        self.attachments = []
        self.body = ""
        self.url = ""
        self.media_comment_id = None
        self.edit_calls: list[dict[str, object]] = []

      def edit(self, **kwargs):
        self.edit_calls.append(kwargs)
        return True

    class FakeAssignment:
      def __init__(self):
        self.id = 575119
        self.name = "Project 1"
        self.points_possible = 100
        self.due_at = datetime(2026, 3, 1, 12, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
        self.pushes: list[dict[str, object]] = []
        self.submissions = {
          3: FakeSubmission(submitted_at="2026-03-01T12:00:00-08:00", submission_type="online_upload"),
          4: FakeSubmission(),
        }

      def push_feedback(self, **kwargs):
        self.pushes.append(kwargs)
        return True

      def get_submission(self, user_id: int):
        return self.submissions[user_id]

    class FakeCourse:
      def __init__(self):
        self.assignment = FakeAssignment()

      def get_students(self, include_names: bool = False):
        return [
          FakeStudent("Jacobs, Samuel", 3),
          FakeStudent("Smith, John", 4),
        ]

      def get_assignment(self, assignment_id: int):
        self.assignment.id = assignment_id
        return self.assignment

    class FakeCanvasInterface:
      last_instance = None

      def __init__(self, *args, **kwargs):
        self.kwargs = kwargs
        self.course = FakeCourse()
        FakeCanvasInterface.last_instance = self

      def get_course(self, course_id: int):
        self.course.course_id = course_id
        return self.course

    with tempfile.TemporaryDirectory() as tempdir:
      root = Path(tempdir)
      assignments_yaml = root / "assignments.yaml"
      name_map = root / "name_map.yaml"
      codepath_csv = root / "codepath-unit1.csv"

      assignments_yaml.write_text(
        yaml.safe_dump(
          {
            "course-id": 32639,
            "unit1": {
              "assignment-id": 575119,
              "base": 10,
              "stretch": 10,
              "ignore": 0,
            }
          }
        ),
        encoding="utf-8",
      )
      name_map.write_text(
        yaml.safe_dump({"CONFIRMED": {"Jacobs, Samuel": ["Sam Jacobs"]}}),
        encoding="utf-8",
      )
      self.write_codepath_csv(
        codepath_csv,
        [
          {
            "First Name": "Sam",
            "Last Name": "Jacobs",
            "Github Username": "sj",
            "Hours Spent": "1",
            "Submitted": "3/1 at 12:30pm PST",
            "Updated": "",
            "Feature Score": "14",
            "Status": "Complete",
            "Assigned Grader": "",
            "Graded At": "",
            "Submission URL": "",
            "Notes": "",
          },
        ],
      )

      with mock.patch.object(codepath_to_canvas, "CanvasInterface", FakeCanvasInterface):
        exit_code = codepath_to_canvas.main(
          [
            "--assignments",
            str(assignments_yaml),
            "--data-dir",
            str(root),
            "--name-map",
            str(name_map),
          ]
        )

      self.assertEqual(exit_code, 0)
      fake_interface = FakeCanvasInterface.last_instance
      self.assertIsNotNone(fake_interface)
      self.assertEqual(len(fake_interface.course.assignment.pushes), 1)
      self.assertEqual(
        fake_interface.course.assignment.submissions[4].edit_calls,
        [{"submission": {"late_policy_status": "missing"}}],
      )

  def test_batch_push_can_use_gradebook_workbook_rows(self) -> None:
    class FakeStudent:
      def __init__(self, name: str, user_id: int):
        self.name = name
        self.user_id = user_id

    class FakeSubmission:
      def __init__(self):
        self.submitted_at = "2026-03-10T12:00:00-07:00"
        self.submission_type = "online_upload"
        self.excused = False
        self.attachments = []
        self.body = ""
        self.url = ""
        self.media_comment_id = None

      def edit(self, **kwargs):
        return True

    class FakeAssignment:
      def __init__(self):
        self.id = 575119
        self.name = "Project 1"
        self.points_possible = 100
        self.due_at = datetime(2026, 3, 10, 12, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
        self.pushes: list[dict[str, object]] = []
        self.submission = FakeSubmission()

      def push_feedback(self, **kwargs):
        self.pushes.append(kwargs)
        return True

      def get_submission(self, user_id: int):
        return self.submission

    class FakeCourse:
      def __init__(self):
        self.assignment = FakeAssignment()

      def get_students(self, include_names: bool = False):
        return [FakeStudent("Jacobs, Samuel", 3)]

      def get_assignment(self, assignment_id: int):
        self.assignment.id = assignment_id
        return self.assignment

    class FakeCanvasInterface:
      last_instance = None

      def __init__(self, *args, **kwargs):
        self.kwargs = kwargs
        self.course = FakeCourse()
        FakeCanvasInterface.last_instance = self

      def get_course(self, course_id: int):
        self.course.course_id = course_id
        return self.course

    with tempfile.TemporaryDirectory() as tempdir:
      root = Path(tempdir)
      assignments_yaml = root / "assignments.yaml"
      name_map = root / "name_map.yaml"
      fake_workbook = root / "Gradebook.xlsx"
      fake_workbook.write_text("", encoding="utf-8")

      assignments_yaml.write_text(
        yaml.safe_dump(
          {
            "course-id": 32639,
            "ASN - 1": {
              "assignment-id": 575119,
              "base": 10,
              "stretch": 10,
              "ignore": 0,
            }
          }
        ),
        encoding="utf-8",
      )
      name_map.write_text(
        yaml.safe_dump({"CONFIRMED": {"Jacobs, Samuel": ["Sam Jacobs"]}}),
        encoding="utf-8",
      )

      with (
        mock.patch.object(codepath_to_canvas, "CanvasInterface", FakeCanvasInterface),
        mock.patch.object(
          codepath_to_canvas,
          "load_gradebook_assignment_rows",
          return_value=(
            [
              {
                "Full Name": "Sam Jacobs",
                "Status": "Complete",
                "Feature Score": "14",
                "Submitted": "3/10 at 12:30pm PDT",
                "Updated": "",
              }
            ],
            None,
          ),
        ),
      ):
        exit_code = codepath_to_canvas.main(
          [
            "--assignments",
            str(assignments_yaml),
            "--xls",
            str(fake_workbook),
            "--name-map",
            str(name_map),
          ]
        )

      self.assertEqual(exit_code, 0)
      fake_interface = FakeCanvasInterface.last_instance
      self.assertIsNotNone(fake_interface)
      self.assertEqual(fake_interface.course.assignment.pushes[0]["score"], 80)

  def test_batch_push_does_not_mark_canvas_only_student_missing_when_canvas_has_submission(self) -> None:
    class FakeStudent:
      def __init__(self, name: str, user_id: int):
        self.name = name
        self.user_id = user_id

    class FakeSubmission:
      def __init__(self, *, submitted_at=None, submission_type="none", excused=False):
        self.submitted_at = submitted_at
        self.submission_type = submission_type
        self.excused = excused
        self.attachments = []
        self.body = ""
        self.url = ""
        self.media_comment_id = None
        self.edit_calls: list[dict[str, object]] = []

      def edit(self, **kwargs):
        self.edit_calls.append(kwargs)
        return True

    class FakeAssignment:
      def __init__(self):
        self.id = 575119
        self.name = "Project 1"
        self.points_possible = 100
        self.due_at = datetime(2026, 3, 1, 12, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
        self.pushes: list[dict[str, object]] = []
        self.submissions = {
          3: FakeSubmission(submitted_at="2026-03-01T12:00:00-08:00", submission_type="online_upload"),
          4: FakeSubmission(submitted_at="2026-03-01T11:45:00-08:00", submission_type="online_upload"),
        }

      def push_feedback(self, **kwargs):
        self.pushes.append(kwargs)
        return True

      def get_submission(self, user_id: int):
        return self.submissions[user_id]

    class FakeCourse:
      def __init__(self):
        self.assignment = FakeAssignment()

      def get_students(self, include_names: bool = False):
        return [
          FakeStudent("Jacobs, Samuel", 3),
          FakeStudent("Smith, John", 4),
        ]

      def get_assignment(self, assignment_id: int):
        self.assignment.id = assignment_id
        return self.assignment

    class FakeCanvasInterface:
      last_instance = None

      def __init__(self, *args, **kwargs):
        self.kwargs = kwargs
        self.course = FakeCourse()
        FakeCanvasInterface.last_instance = self

      def get_course(self, course_id: int):
        self.course.course_id = course_id
        return self.course

    with tempfile.TemporaryDirectory() as tempdir:
      root = Path(tempdir)
      assignments_yaml = root / "assignments.yaml"
      name_map = root / "name_map.yaml"
      codepath_csv = root / "codepath-unit1.csv"

      assignments_yaml.write_text(
        yaml.safe_dump(
          {
            "course-id": 32639,
            "unit1": {
              "assignment-id": 575119,
              "base": 10,
              "stretch": 10,
              "ignore": 0,
            }
          }
        ),
        encoding="utf-8",
      )
      name_map.write_text(
        yaml.safe_dump({"CONFIRMED": {"Jacobs, Samuel": ["Sam Jacobs"]}}),
        encoding="utf-8",
      )
      self.write_codepath_csv(
        codepath_csv,
        [
          {
            "First Name": "Sam",
            "Last Name": "Jacobs",
            "Github Username": "sj",
            "Hours Spent": "1",
            "Submitted": "3/1 at 12:30pm PST",
            "Updated": "",
            "Feature Score": "14",
            "Status": "Complete",
            "Assigned Grader": "",
            "Graded At": "",
            "Submission URL": "",
            "Notes": "",
          },
        ],
      )

      with mock.patch.object(codepath_to_canvas, "CanvasInterface", FakeCanvasInterface):
        exit_code = codepath_to_canvas.main(
          [
            "--assignments",
            str(assignments_yaml),
            "--data-dir",
            str(root),
            "--name-map",
            str(name_map),
          ]
        )

      self.assertEqual(exit_code, 0)
      fake_interface = FakeCanvasInterface.last_instance
      self.assertIsNotNone(fake_interface)
      self.assertEqual(len(fake_interface.course.assignment.pushes), 1)
      self.assertEqual(fake_interface.course.assignment.submissions[4].edit_calls, [])

  def test_batch_push_does_not_partially_push_when_preflight_fails(self) -> None:
    class FakeStudent:
      def __init__(self, name: str, user_id: int):
        self.name = name
        self.user_id = user_id

    class FakeAssignment:
      def __init__(self, assignment_id: int, name: str):
        self.id = assignment_id
        self.name = name
        self.points_possible = 100
        self.pushes: list[dict[str, object]] = []

      def push_feedback(self, **kwargs):
        self.pushes.append(kwargs)
        return True

    class FakeCourse:
      def __init__(self):
        self.assignments = {
          575119: FakeAssignment(575119, "Project 1"),
          575124: FakeAssignment(575124, "Project 5"),
        }

      def get_students(self, include_names: bool = False):
        return [
          FakeStudent("Jacobs, Samuel", 3),
          FakeStudent("John Smith", 4),
        ]

      def get_assignment(self, assignment_id: int):
        return self.assignments[assignment_id]

    class FakeCanvasInterface:
      last_instance = None

      def __init__(self, *args, **kwargs):
        self.kwargs = kwargs
        self.course = FakeCourse()
        FakeCanvasInterface.last_instance = self

      def get_course(self, course_id: int):
        self.course.course_id = course_id
        return self.course

    with tempfile.TemporaryDirectory() as tempdir:
      root = Path(tempdir)
      assignments_yaml = root / "assignments.yaml"
      name_map = root / "name_map.yaml"
      unit1_csv = root / "codepath-unit1.csv"
      unit5_csv = root / "codepath-unit5.csv"

      assignments_yaml.write_text(
        yaml.safe_dump(
          {
            "course-id": 32639,
            "unit1": {
              "assignment-id": 575119,
              "base": 10,
              "stretch": 10,
              "ignore": 0,
            },
            "unit5": {
              "assignment-id": 575124,
              "base": 10,
              "stretch": 10,
              "ignore": 0,
            },
          }
        ),
        encoding="utf-8",
      )
      name_map.write_text(
        yaml.safe_dump({"CONFIRMED": {"Jacobs, Samuel": ["Sam Jacobs"]}}),
        encoding="utf-8",
      )
      self.write_codepath_csv(
        unit1_csv,
        [
          {
            "First Name": "Jon",
            "Last Name": "Smyth",
            "Github Username": "js",
            "Hours Spent": "1",
            "Submitted": "",
            "Updated": "",
            "Feature Score": "14",
            "Status": "Complete",
            "Assigned Grader": "",
            "Graded At": "",
            "Submission URL": "",
            "Notes": "",
          },
        ],
      )
      self.write_codepath_csv(
        unit5_csv,
        [
          {
            "First Name": "Sam",
            "Last Name": "Jacobs",
            "Github Username": "sj",
            "Hours Spent": "1",
            "Submitted": "",
            "Updated": "",
            "Feature Score": "14",
            "Status": "Complete",
            "Assigned Grader": "",
            "Graded At": "",
            "Submission URL": "",
            "Notes": "",
          },
        ],
      )

      with mock.patch.object(codepath_to_canvas, "CanvasInterface", FakeCanvasInterface):
        exit_code = codepath_to_canvas.main(
          [
            "--assignments",
            str(assignments_yaml),
            "--data-dir",
            str(root),
            "--name-map",
            str(name_map),
            "--stretch-weight",
            "0.5",
          ]
        )

      self.assertEqual(exit_code, 1)
      fake_interface = FakeCanvasInterface.last_instance
      self.assertEqual(fake_interface.course.assignments[575119].pushes, [])
      self.assertEqual(fake_interface.course.assignments[575124].pushes, [])

  def test_default_name_map_path_is_persisted(self) -> None:
    with tempfile.TemporaryDirectory() as tempdir:
      root = Path(tempdir)
      old_cwd = Path.cwd()
      try:
        os.chdir(root)
        codepath_csv = root / "codepath.csv"
        canvas_csv = root / "canvas.csv"

        self.write_codepath_csv(
          codepath_csv,
          [
            {
              "First Name": "Sam",
              "Last Name": "Jacobs",
              "Github Username": "sj",
              "Hours Spent": "1",
              "Submitted": "",
              "Updated": "",
              "Feature Score": "14",
              "Status": "Complete",
              "Assigned Grader": "",
              "Graded At": "",
              "Submission URL": "",
              "Notes": "",
            },
          ],
        )
        self.write_canvas_csv(
          canvas_csv,
          [
            ["    Points Possible", "", "", "", "", "100"],
            ["Samuel Jacobs", "3", "u3", "u3", "sec", ""],
          ],
        )

        with mock.patch("builtins.input", side_effect=["1"]), mock.patch("sys.stdin.isatty", return_value=True):
          exit_code = codepath_to_canvas.main(
            [
              "--in",
              str(codepath_csv),
              "--canvas",
              str(canvas_csv),
              "--base-points",
              "10",
              "--stretch-points",
              "10",
              "--stretch-weight",
              "0.5",
              "--prompt-for-matches",
            ]
          )

        self.assertEqual(exit_code, 0)
        written_map = yaml.safe_load((root / "name_map.yaml").read_text(encoding="utf-8"))
        self.assertEqual(written_map["CONFIRMED"]["Samuel Jacobs"], ["Sam Jacobs"])
      finally:
        os.chdir(old_cwd)

  def write_codepath_csv(self, path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
      writer = csv.DictWriter(handle, fieldnames=CODEPATH_HEADER)
      writer.writeheader()
      writer.writerows(rows)

  def write_canvas_csv(self, path: Path, rows: list[list[str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
      writer = csv.writer(handle)
      writer.writerow(CANVAS_HEADER)
      writer.writerows(rows)


if __name__ == "__main__":
  unittest.main()
