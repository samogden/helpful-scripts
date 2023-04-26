#!env python
import argparse
import json
import os.path
from collections import defaultdict

import pandas as pd

import logging
logging.basicConfig()
log = logging.getLogger("PeerEval")
log.setLevel(logging.DEBUG)

class Evaluation(object):
  def __init__(self, name, rating, explanation, self_eval_bool=False):
    self.self_eval = self_eval_bool
    self.name = fix_names(name.strip().title())
    self.rating = rating
    self.explanation = explanation

def fix_names(in_name):
  names_json = json.load(open("student_names.json"))
  names = names_json["names"]
  if in_name in names:
    return names[in_name]
  return in_name

def parse_csv(csv_file):
  df = pd.read_csv(csv_file)
  log.debug(df)
  
  assignment_evals = defaultdict(list)
  
  columns = df.columns
  for row_i, row in df.iterrows():
    programming_assignment = row["Programming Assignment Number"]
    i = 0
    while (i < len(columns)):
      if "First and Last Name" in columns[i]:
        if "Rating" in columns[i+1]:
          name = row[columns[i]]
          if name == "" or name == "none" or pd.isnull(name):
            break
          rating = row[columns[i+1]]
          explanation = row[columns[i+2]]
          assignment_evals[programming_assignment].append(
            Evaluation(name, rating, explanation, False)
          )
        else:
          name = row[columns[i]]
          rating = row[columns[i+3]]
          explanation = row[columns[i+4]]
          assignment_evals[programming_assignment].append(
            Evaluation(name, rating, explanation, True)
          )
      i += 1
  return assignment_evals

def parse_evals(evals: list[Evaluation], max_points):
  per_student_evals = defaultdict(list)
  for eval in evals:
    per_student_evals[eval.name].append(eval)
  for name in sorted(per_student_evals.keys(), key=(lambda n: (n.split()[-1], tuple(n.split()[:-1])))):
    total_score = 0
    num_peer_reviews = 0
    has_self = False
    for review in per_student_evals[name]:
      if review.self_eval:
        has_self = True
      else:
        total_score += review.rating
        num_peer_reviews += 1
    try:
      score = convert_to_points(total_score / num_peer_reviews, max_points)
      if has_self:
        log.debug(f"{name} -> {score:0.2f}" )
      else:
        log.debug(f"**{name} -> {score / 2.0:0.2f}" )
    except ZeroDivisionError:
      log.warning(f"No peer reviews for {name}")

def convert_to_points(score, max_points):
  if score >= 3:
    return max_points
  if score <= 1:
    return 0.0
  return (score) / 3 * max_points

def get_flags():
  parser = argparse.ArgumentParser()
  parser.add_argument("--input_csv", required=True)
  parser.add_argument("--max_points", required=True)
  
  return parser.parse_args()

def main():
  
  flags = get_flags()
  
  assignment_evals = parse_csv(os.path.expanduser(flags.input_csv))
  #log.debug(assignment_evals.values())
  for assignment, eval in assignment_evals.items():
    log.debug("")
    log.debug(f"Assignment: {assignment}")
    parse_evals(eval, flags.max_points)


if __name__ == "__main__":
  main()