import csv
import tempfile
import unittest
from pathlib import Path
from unittest import mock
import os

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

    class FakeAssignment:
      def __init__(self):
        self.id = 575119
        self.name = "Project 1"
        self.points_possible = 100
        self.pushes: list[dict[str, object]] = []

      def push_feedback(self, **kwargs):
        self.pushes.append(kwargs)
        return True

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
      self.assertIn("Base points:", fake_interface.course.assignment.pushes[0]["comments"])
      self.assertIn("Stretch points:", fake_interface.course.assignment.pushes[0]["comments"])

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
