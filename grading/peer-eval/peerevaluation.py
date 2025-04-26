#!env python
import argparse
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
logging.basicConfig()
log = logging.getLogger("PeerEval")
log.setLevel(logging.DEBUG)

class Evaluation(object):
  def __init__(self, name, rating, explanation, self_eval_bool=False):
    self.self_eval = self_eval_bool
    self.name = name.strip()
    self.rating = rating
    self.explanation = explanation
    self.definitive_name = self_eval_bool # whether a name has been definitely matched or not


def load_name_file(name_yaml) -> Dict[str,str]:
  name_correction_dict = {}
  
  if not os.path.exists(name_yaml):
    log.warning("No name correction file passed in")
    return name_correction_dict
  with open(name_yaml) as fid:
    names = yaml.safe_load(fid)
    for definitive_names, list_of_alternatives in names.items():
      for alternative in list_of_alternatives:
        name_correction_dict[alternative] = definitive_names
  
  return name_correction_dict


def parse_csv(csv_file, student_names_file, assignment="general") -> List[Evaluation]:
  df = pd.read_csv(csv_file)
  #df['Timestamp'] = pd.to_datetime(df['Timestamp'])

  df = df[~(pd.to_datetime(df['Timestamp']) < (pd.Timestamp.now() - pd.Timedelta(weeks=4)))]
  
  assignment_evals = defaultdict(list)
  
  student_self_names = []
  
  columns = df.columns
  for row_i, row in df.iterrows():
    try:
      programming_assignment = row["Programming Assignment Number"]
    except KeyError:
      programming_assignment = "general"
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
          student_self_names.append(name)
      i += 1
    
  return assignment_evals[assignment]


def correct_names(evaluations: List[Evaluation], name_correction_dict):
  log.info("Correcting names...")
  self_names = [eval.name for eval in evaluations if eval.self_eval]
  log.debug(self_names)
  
  # Update names based on passed-in dictionary
  for eval in filter(lambda e: not e.definitive_name, evaluations):
    try:
      eval.name = name_correction_dict[eval.name]
      eval.definitive_name = True
    except KeyError:
      log.debug(f"No match found in correction dictionary for \"{eval.name}\"")
  
  # Update names programatically
  name_corrections_made = defaultdict(list)
  for eval in filter(lambda e: not e.definitive_name, evaluations):
    best_match = max(self_names, key=lambda n: fuzzywuzzy.fuzz.ratio(n, eval.name))
    if fuzzywuzzy.fuzz.ratio(best_match, eval.name) >= 80:
      log.debug(f"Correcting \"{eval.name}\" --> \"{best_match}\" ({fuzzywuzzy.fuzz.ratio(best_match, eval.name)})")
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
      for name in sorted(self_names)
    }
    dict_for_yaml["UNMATCHED"] = sorted(set(unmatched_names))
    print(yaml.dump(
      dict_for_yaml,
      default_flow_style=False,
      sort_keys=False,  # Preserve key order
      indent=2,         # Set custom indentation
    ))
  

def parse_evals(evals: list[Evaluation], max_points):
  per_student_evals = defaultdict(list)
  for eval in evals:
    per_student_evals[eval.name].append(eval)
  for name in sorted(per_student_evals.keys()): #, key=(lambda n: (n.split()[-1], tuple(n.split()[:-1])))):
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
        print(f"{name} -> {score:0.2f}" )
      else:
        print(f"{colorama.Fore.LIGHTRED_EX}{colorama.Style.BRIGHT}*{name} -> {score / 2.0:0.2f}{colorama.Style.RESET_ALL}")
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
  parser.add_argument("--max_points", required=True, type=int)
  parser.add_argument("--student_names_file", default="names.yaml")
  
  return parser.parse_args()

def main():
  
  flags = get_flags()
  
  name_correction_dict = load_name_file(flags.student_names_file)
  
  # Load the evaluations up, so I have a list of evaluation objects
  assignment_evals = parse_csv(os.path.expanduser(flags.input_csv), flags.student_names_file)
  
  # Correct names
  correct_names(assignment_evals, name_correction_dict)
  if any(map(lambda e: not e.definitive_name, assignment_evals)):
    log.error("Some unmatched names remain.  Please fix using the above YAML and retry.")
    return
  
  parse_evals(
    assignment_evals,
    flags.max_points
  )
  
  return
  
  
if __name__ == "__main__":
  main()