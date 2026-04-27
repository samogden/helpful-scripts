#!env python
import argparse
import csv
import json
import os.path
import re
from collections import defaultdict
from typing import List, Dict

import fuzzywuzzy.fuzz
import yaml
import colorama

import pandas as pd

import logging
logging.basicConfig(format="%(levelname)s:%(name)s:%(message)s")
log = logging.getLogger("PeerEval")
log.setLevel(logging.WARNING)

colorama.init()

class Evaluation(object):
  def __init__(self, name, rating, explanation, self_eval_bool=False, teammates=None):
    self.self_eval = self_eval_bool
    self.name = name.strip()
    self.rating = rating
    self.explanation = explanation
    self.teammates = list(teammates or [])
    self.definitive_name = self_eval_bool # whether a name has been definitely matched or not


def normalize_name(name: str) -> str:
  return re.sub(r"\s+", " ", str(name).strip()).lower()


LAST_NAME_PARTICLES = {
  "de", "del", "della", "di", "la", "le", "van", "von", "der", "den",
  "da", "dos", "das", "du", "st", "st.", "bin", "ibn", "al"
}

NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def name_sort_key(name: str):
  raw = str(name).strip()
  if "," in raw:
    last, rest = [part.strip() for part in raw.split(",", 1)]
    return (normalize_name(last), normalize_name(rest))

  tokens = [token for token in re.findall(r"[A-Za-z0-9']+", raw) if token]
  if not tokens:
    return ("", "")
  if len(tokens) == 1:
    return (normalize_name(tokens[0]), "")

  suffix = tokens[-1].rstrip(".").lower()
  if suffix in NAME_SUFFIXES and len(tokens) >= 2:
    tokens = tokens[:-1]

  if len(tokens) >= 3 and tokens[-2].lower() in LAST_NAME_PARTICLES:
    last_name = " ".join(tokens[-2:])
    first_names = " ".join(tokens[:-2])
  else:
    last_name = tokens[-1]
    first_names = " ".join(tokens[:-1])

  return (normalize_name(last_name), normalize_name(first_names))


def load_name_file(name_yaml) -> Dict[str,str]:
  name_correction_dict = {}
  
  if not os.path.exists(name_yaml):
    log.warning("No name correction file passed in")
    return name_correction_dict
  with open(name_yaml) as fid:
    names = yaml.safe_load(fid)
    for definitive_names, list_of_alternatives in names.items():
      # Treat the YAML key as a valid match target too, not only the aliases.
      name_correction_dict[definitive_names] = definitive_names
      for alternative in list_of_alternatives:
        name_correction_dict[alternative] = definitive_names
  
  return name_correction_dict


def normalize_dict_keys(source: Dict[str, str]) -> Dict[str, str]:
  return {normalize_name(k): v for k, v in source.items()}


def resolve_name_with_corrections(name: str, name_correction_dict, normalized_name_correction_dict):
  try:
    return name_correction_dict[name]
  except KeyError:
    normalized_name = normalize_name(name)
    return normalized_name_correction_dict.get(normalized_name, name)


def parse_csv(csv_file, class_filter=None, assignment_filter=None) -> Dict[str, List[Evaluation]]:
  df = pd.read_csv(csv_file)

  df["_parsed_timestamp"] = pd.to_datetime(df["Timestamp"], format="mixed", errors="coerce")
  df = df[df["_parsed_timestamp"].notna()].copy()
  df = df[df["_parsed_timestamp"] >= (pd.Timestamp.now() - pd.Timedelta(weeks=4))]
  df = df.copy()
  df = df.sort_values("_parsed_timestamp", ascending=False)

  if "What class is this for?" not in df.columns:
    df["What class is this for?"] = "general"

  assignment_evals = defaultdict(list)
  seen_submissions = set()
  normalized_class_filter = normalize_name(class_filter) if class_filter else None
  normalized_assignment_filter = normalize_name(assignment_filter) if assignment_filter else None

  def clean_value(value):
    if pd.isnull(value):
      return ""
    return str(value).strip()

  def get_first_present(row, candidates):
    for candidate in candidates:
      if candidate in row.index:
        return row[candidate]
    raise KeyError(candidates[0])

  for row_i, row in df.iterrows():
    try:
      class_name = clean_value(get_first_present(
        row,
        ["What class is this for?", "Class"]
      ))
      programming_assignment = clean_value(get_first_present(
        row,
        ["Programming Assignment Number", "What project is this for?"]
      ))
    except KeyError:
      programming_assignment = "general"
      class_name = "general"

    class_name = clean_value(class_name)
    programming_assignment = clean_value(programming_assignment)
    if not class_name or not programming_assignment:
      log.debug("Skipping row with blank class or assignment")
      continue
    if normalized_class_filter and normalize_name(class_name) != normalized_class_filter:
      continue
    if normalized_assignment_filter and normalize_name(programming_assignment) != normalized_assignment_filter:
      continue
    assignment_key = f"{class_name} :: {programming_assignment}"

    row_key = (
      normalize_name(class_name),
      normalize_name(programming_assignment),
      normalize_name(get_first_present(
        row,
        ["What is your name?", "First and Last Name"]
      ))
    )
    if row_key in seen_submissions:
      log.debug(f"Skipping duplicate submission for {row_key}")
      continue
    seen_submissions.add(row_key)

    self_name = clean_value(get_first_present(
      row,
      ["What is your name?", "First and Last Name"]
    ))
    self_rating = get_first_present(
      row,
      ["How would you rate your own performance?", "Rating"]
    )
    teammates = []
    self_eval = None

    def add_teammate(name):
      if len(name) < 2 or name.lower() in {"none", "n/a", "na"} or name.lower().startswith("no "):
        return
      teammates.append(name)

    if self_name and self_name.lower() != "none":
      self_eval = Evaluation(self_name, self_rating, "", True)
      self_eval.teammates = teammates
      assignment_evals[assignment_key].append(self_eval)

    for column in df.columns:
      if not column.startswith("What is your teammate's name"):
        continue
      suffix = column[len("What is your teammate's name"):]
      rating_col = f"How would you rate their performance{suffix}"
      comment_col = f"Any specific comments?{suffix}"
      name = clean_value(row[column])
      if len(name) < 2 or name.lower() == "none" or name.lower().startswith("no "):
        continue
      add_teammate(name)
      rating = row[rating_col] if rating_col in row.index else ""
      explanation = clean_value(row[comment_col]) if comment_col in row.index else ""
      assignment_evals[assignment_key].append(
        Evaluation(name, rating, explanation, False)
      )
  
  return assignment_evals


def parse_old_online_csv(csv_file, class_filter=None, assignment_filter=None) -> Dict[str, List[Evaluation]]:
  assignment_evals = defaultdict(list)
  seen_submissions = set()
  normalized_class_filter = normalize_name(class_filter) if class_filter else None
  normalized_assignment_filter = normalize_name(assignment_filter) if assignment_filter else None

  def clean_value(value):
    if pd.isnull(value):
      return ""
    return str(value).strip()

  def get_cell(row, index):
    if index >= len(row):
      return ""
    return clean_value(row[index])

  with open(csv_file, newline="") as fid:
    reader = csv.reader(fid)
    headers = next(reader, [])
    if not headers:
      return assignment_evals

    for row in reader:
      if not row:
        continue

      parsed_timestamp = pd.to_datetime(get_cell(row, 0), format="mixed", errors="coerce")
      if pd.isna(parsed_timestamp):
        continue
      if parsed_timestamp < (pd.Timestamp.now() - pd.Timedelta(weeks=4)):
        continue

      class_name = "general"
      programming_assignment = "old-online"
      if normalized_class_filter and normalize_name(class_name) != normalized_class_filter:
        continue
      if normalized_assignment_filter and normalize_name(programming_assignment) != normalized_assignment_filter:
        continue

      assignment_key = f"{class_name} :: {programming_assignment}"

      self_name = get_cell(row, 2)
      self_rating = get_cell(row, 4)
      self_explanation = get_cell(row, 5)
      teammates = []
      self_eval = None

      row_key = (
        normalize_name(self_name),
        normalize_name(get_cell(row, 3)),
        normalize_name(programming_assignment),
      )
      if row_key in seen_submissions:
        log.debug(f"Skipping duplicate submission for {row_key}")
        continue
      seen_submissions.add(row_key)

      if self_name and self_name.lower() != "none":
        self_eval = Evaluation(self_name, self_rating, self_explanation, True)
        assignment_evals[assignment_key].append(self_eval)

      # Legacy online forms repeat teammate fields in name/rating/comment triplets.
      for index in range(6, len(row), 3):
        name = get_cell(row, index)
        if len(name) < 2 or name.lower() in {"none", "n/a", "na"} or name.lower().startswith("no "):
          continue
        teammates.append(name)
        rating = get_cell(row, index + 1)
        explanation = get_cell(row, index + 2)
        assignment_evals[assignment_key].append(
          Evaluation(name, rating, explanation, False)
        )
      if self_eval is not None:
        self_eval.teammates = teammates

  return assignment_evals


def correct_names(evaluations: List[Evaluation], name_correction_dict):
  log.info("Correcting names...")
  normalized_name_correction_dict = normalize_dict_keys(name_correction_dict)

  def resolve(name: str):
    return resolve_name_with_corrections(name, name_correction_dict, normalized_name_correction_dict)

  # First pass: apply any explicit YAML match to every evaluation, including self-evals.
  for eval in evaluations:
    resolved_name = resolve(eval.name)
    if resolved_name != eval.name:
      eval.name = resolved_name
      eval.definitive_name = True
    else:
      log.debug(f"No match found in correction dictionary for \"{eval.name}\"")

  # Build the self-name reference list from canonicalized self-evals.
  self_name_lookup = {}
  self_names = []
  for eval in evaluations:
    if eval.self_eval:
      normalized = normalize_name(eval.name)
      if normalized not in self_name_lookup:
        self_name_lookup[normalized] = eval.name
        self_names.append(eval.name)
      eval.teammates = [resolve(name) for name in eval.teammates]
  log.debug(self_names)

  # Update names programatically for peer evaluations that still remain ambiguous.
  name_corrections_made = defaultdict(list)
  for eval in filter(lambda e: not e.definitive_name, evaluations):
    if not self_names:
      break
    best_match = max(
      self_names,
      key=lambda n: max(
        fuzzywuzzy.fuzz.ratio(normalize_name(n), normalize_name(eval.name)),
        fuzzywuzzy.fuzz.partial_ratio(normalize_name(n), normalize_name(eval.name)),
      )
    )
    best_score = max(
      fuzzywuzzy.fuzz.ratio(normalize_name(best_match), normalize_name(eval.name)),
      fuzzywuzzy.fuzz.partial_ratio(normalize_name(best_match), normalize_name(eval.name)),
    )
    if best_score >= 80:
      log.debug(f"Correcting \"{eval.name}\" --> \"{best_match}\" ({best_score})")
      name_corrections_made[best_match].append(eval.name)
      eval.name = best_match
      eval.definitive_name = True
  
  # List out names that weren't matched, if any
  unmatched_names = [eval.name for eval in evaluations if not eval.definitive_name]
  if len(unmatched_names) == 0:
    log.info("All names matched, continuing")
  else:
    log.warning("Some names unmmatched, see below yaml for details and to pass in manual overrides")
    dict_for_yaml = {
      name : list(set([name] + name_corrections_made[name]))
      for name in sorted(self_names, key=name_sort_key)
    }
    dict_for_yaml["UNMATCHED"] = sorted(set(unmatched_names))
    print(yaml.dump(
      dict_for_yaml,
      default_flow_style=False,
      sort_keys=False,  # Preserve key order
      indent=2,         # Set custom indentation
    ))
  

def summarize_evals(evals: list[Evaluation], max_points):
  per_student_evals = defaultdict(list)
  for eval in evals:
    per_student_evals[eval.name].append(eval)
  rows = []
  for name in sorted(per_student_evals.keys(), key=name_sort_key):
    total_score = 0
    num_peer_reviews = 0
    has_self = False
    expected_teammates = []
    for review in per_student_evals[name]:
      if review.self_eval:
        has_self = True
        if review.teammates and not expected_teammates:
          expected_teammates = review.teammates
      else:
        try:
          total_score += float(review.rating)
          num_peer_reviews += 1
        except (TypeError, ValueError):
          log.debug(f"Skipping non-numeric rating for {name}: {review.rating!r}")
    if num_peer_reviews == 0:
      rows.append({
        "name": name,
        "peer_avg": None,
        "final_score": None,
        "percent": None,
        "num_peer_reviews": 0,
        "has_self": has_self,
        "expected_teammates": expected_teammates,
        "note": "no peer reviews",
      })
      continue

    peer_avg = total_score / num_peer_reviews
    score = convert_to_points(peer_avg, max_points)
    final_score = score if has_self else score / 2.0
    rows.append({
      "name": name,
      "peer_avg": peer_avg,
      "final_score": final_score,
      "percent": (final_score / max_points) * 100 if max_points else 0,
      "num_peer_reviews": num_peer_reviews,
      "has_self": has_self,
      "expected_teammates": expected_teammates,
      "note": "" if has_self else "missing self eval",
    })
  return rows


def strip_ansi(text):
  return re.sub(r"\x1b\[[0-9;]*m", "", text)


def pad_cell(text, width):
  plain = str(text)
  return plain + " " * max(0, width - len(strip_ansi(plain)))


def render_score_table(assignment, rows, max_points):
  headers = ["Student", "Peer Avg", "Final", "Pct", "Peer Reviews", "Self", "Note", "Expected Teammates"]
  display_rows = []
  for row in rows:
    if row["peer_avg"] is None:
      peer_avg = "--"
      final_score = "--"
      pct = "--"
    else:
      peer_avg = f"{row['peer_avg']:.2f}"
      final_score = f"{row['final_score']:.2f}/{max_points:.2f}"
      pct = f"{row['percent']:.0f}%"
    expected_teammates = ", ".join(row["expected_teammates"]) if row["expected_teammates"] else "--"
    display_rows.append({
      "Student": row["name"],
      "Peer Avg": peer_avg,
      "Final": final_score,
      "Pct": pct,
      "Peer Reviews": str(row["num_peer_reviews"]),
      "Self": "Y" if row["has_self"] else "N",
      "Note": row["note"],
      "Expected Teammates": expected_teammates,
      "is_perfect": row["peer_avg"] is not None and round(row["percent"] or 0) == 100,
    })

  widths = {header: len(header) for header in headers}
  for row in display_rows:
    for header in headers:
      widths[header] = max(widths[header], len(str(row[header])))

  def format_row(row, colorize=False):
    cells = []
    for header in headers:
      cell = pad_cell(row[header], widths[header])
      if colorize and header in {"Final", "Pct"} and not row["is_perfect"]:
        cell = f"{colorama.Fore.LIGHTRED_EX}{colorama.Style.BRIGHT}{cell}{colorama.Style.RESET_ALL}"
      cells.append(cell)
    return " | ".join(cells)

  separator = "-+-".join("-" * widths[header] for header in headers)
  print(f"\n== {assignment} ==")
  print(format_row({header: header for header in headers}))
  print(separator)
  for row in display_rows:
    print(format_row(row, colorize=True))

def convert_to_points(score, max_points):
  if score >= 3:
    return max_points
  if score <= 1:
    return 0.0
  return (score) / 3 * max_points

def get_flags():
  parser = argparse.ArgumentParser()
  parser.add_argument("--input_csv", required=True)
  parser.add_argument("--max_points", required=True, type=int)
  parser.add_argument("--student_names_file", default="names.yaml")
  parser.add_argument("--assignment", default=None, help="Only process one programming assignment name")
  parser.add_argument("--class_name", default=None, help="Only process one class name")
  parser.add_argument("--old-online", action="store_true", help="Parse legacy online peer-evaluation CSVs")
  parser.add_argument("--verbose", action="store_true", help="Show informational logging")
  
  return parser.parse_args()

def main():
  
  flags = get_flags()

  log.setLevel(logging.INFO if flags.verbose else logging.WARNING)
  
  name_correction_dict = load_name_file(flags.student_names_file)
  
  # Load the evaluations up, grouped by class and assignment.
  input_csv = os.path.expanduser(flags.input_csv)
  if flags.old_online:
    evaluations_by_assignment = parse_old_online_csv(
      input_csv,
      class_filter=flags.class_name,
      assignment_filter=flags.assignment,
    )
  else:
    evaluations_by_assignment = parse_csv(
      input_csv,
      class_filter=flags.class_name,
      assignment_filter=flags.assignment,
    )

  available_assignments = sorted(evaluations_by_assignment.keys())
  for assignment in available_assignments:
    assignment_evals = evaluations_by_assignment[assignment]

    log.info(f"Processing assignment: {assignment}")

    # Correct names
    correct_names(assignment_evals, name_correction_dict)
    if any(map(lambda e: not e.definitive_name, assignment_evals)):
      log.warning("Some unmatched names remain. Continuing with partial results.")

    rows = summarize_evals(
      assignment_evals,
      flags.max_points
    )
    render_score_table(assignment, rows, flags.max_points)
  
  return
  
  
if __name__ == "__main__":
  main()
