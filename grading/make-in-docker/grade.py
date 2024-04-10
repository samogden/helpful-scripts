#!env python
import argparse
import collections
import difflib
import io
import json
import logging
import os
import pathlib
import random
import shutil
import subprocess
import tarfile
import tempfile
from typing import Dict, List

import docker
import pandas
import numpy as np
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

logging.basicConfig()
log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

client = docker.from_env()

def parse_flags():
  parser = argparse.ArgumentParser()
  parser.add_argument("--csv_in", default="/Users/ssogden/scratch/csT334/2023-09-29T2137_Grades-CST334-M_01-02_FA23.csv")
  parser.add_argument("--path_to_files", default="/Users/ssogden/scratch/csT334/submissions")
  parser.add_argument("--assignment_name", default="PA1 - Intro to C and Processes (code)")
  parser.add_argument("--num_repeats", default=3)
  parser.add_argument("--use_max", action="store_true")
  parser.add_argument("--tag", default=["main"], action="append", dest="tags")
  parser.add_argument("--assignment", default="PA1")
  parser.add_argument("--github_repo", default="https://github.com/samogden/CST334-assignments.git")
  
  parser.add_argument("--confusion_only", action="store_true")
  parser.add_argument("--threshold", type=float, default=0.8)
  
  parser.add_argument("--debug", action="store_true")
  
  args = parser.parse_args()
  
  return args

def parse_csv(path_to_csv):
  df = pandas.read_csv(path_to_csv)
  #df = df.iloc[:,:6]
  return df


def get_student_files(submissions_dir) -> Dict[str,Dict[str,str]]:
  submission_files = collections.defaultdict(dict)
  files = os.listdir(submissions_dir)
  for f in files:
    log.debug(f"f: {f}")
    if "student_code" not in f:
      continue
    student_name = f.split("_")[0]
    student_name_id = f.split("_")[1] if "LATE" not in f else f.split("_")[2]
    extension = pathlib.Path(f).suffix
    log.debug(f"{f} : {student_name} {extension}")
    submission_files[(student_name, student_name_id)][extension] = f
  return submission_files


def build_docker_image(github_repo="https://github.com/samogden/CST334-assignments.git"):
  
  docker_file = io.BytesIO(f"""
  FROM samogden/csumb:cst334
  RUN git clone {github_repo} /tmp/grading/
  WORKDIR /tmp/grading
  CMD ["/bin/bash"]
  """.encode())
  
  image, logs = client.images.build(
    fileobj=docker_file,
    tag="grading",
    pull=True,
    nocache=True
  )
  log.debug(logs)
  return image

def run_docker_with_archive(image, student_files_dir, tag_to_test, programming_assignment):

  tarstream = io.BytesIO()
  with tarfile.open(fileobj=tarstream, mode="w") as tarhandle:
    for f in [os.path.join(student_files_dir, f) for f in os.listdir(student_files_dir)]:
      tarhandle.add(f, arcname=os.path.basename(f))
  tarstream.seek(0)

  container = client.containers.run(
    image=image,
    detach=True,
    tty=True
  )
  try:
    container.put_archive(f"/tmp/grading/programming-assignments/{programming_assignment}/src", tarstream)
    
    exit_code, output = container.exec_run(f"ls -l /tmp/grading/programming-assignments/{programming_assignment}/")
    log.debug(output.decode())
    exit_code, output = container.exec_run(f"tree /tmp/grading/programming-assignments/{programming_assignment}/")
    log.debug(output.decode())
    
    
    container.exec_run(f"bash -c 'git checkout {tag_to_test}'")
    
    run_str = f"""
      bash -c '
        cd /tmp/grading/programming-assignments/{programming_assignment} ;
        timeout 600 python ../../helpers/grader.py --output /tmp/results.json ;
      '
      """
    log.debug(f"run_str: {run_str}")
    exit_code, output = container.exec_run(run_str)
    try:
      bits, stats = container.get_archive("/tmp/results.json")
    except docker.errors.NotFound:
      return { "score" : 0.0, "build_logs" : None}
    f = io.BytesIO()
    for chunk in bits:
      f.write(chunk)
    f.seek(0)
    
    with tarfile.open(fileobj=f, mode="r") as tarhandle:
      results_f = tarhandle.getmember("results.json")
      f = tarhandle.extractfile(results_f)
      f.seek(0)
      results = json.loads(f.read().decode())
  finally:
    container.stop(timeout=1)
    container.remove()
    
  log.debug(f"results: {results}")
  
  return results
  

def write_feedback(student, results):
  with open(os.path.join("feedback", f"{student}.txt"), 'w') as fid:
    fid.write(f"Score: {results['score']}")
    fid.write("\n\n")
    
    if "suites" in results:
      for suite in results["suites"]:
        fid.write(f"SUITE: {suite}\n")
        fid.write("  PASSED:\n")
        for t in results["suites"][suite]["PASSED"]:
          fid.write(f"    {t}\n")
        fid.write("  FAILED:\n")
        for t in results["suites"][suite]["FAILED"]:
          fid.write(f"    {t}\n")
      fid.write("\n\n")
    
    fid.write("BUILD INFO:\n")
    try:
      if results['build_logs'] is None:
        fid.write("No build results available.  Did it time out?")
      else:
        fid.write(json.decoder.JSONDecoder().decode(results['build_logs'][0]))
    except (json.decoder.JSONDecodeError):
      fid.write(results['build_logs'])
    except TypeError:
      fid.write(results['build_logs'][0].decode())
    fid.write("\n")

def get_assignment_column_name(columns, assignment_name):
  for i, name in enumerate(columns):
    if name.startswith(assignment_name):
      return i, name



def calc_similarity(submission1, submission2):
  p = subprocess.run(["diff", "-w", submission1, submission2], capture_output=True)
  # print(f"p -> {p}")
  return p.stdout.decode().count('\n')

def calc_similarity_python(submission1, submission2):
  def clean_line(line: str):
    line = line.strip()
    line = line.split('//')[0]
    # if line == "}": return ""
    return line
  def parse_lines(lines: List[str]):
    parsed_lines = []
    for line in lines:
      line = clean_line(line)
      if line == "":
        continue
      parsed_lines.append(line)
    return parsed_lines
  
  with open(submission1) as fid:
    lines1 = parse_lines(fid.readlines())
  with open(submission2) as fid:
    lines2 = parse_lines(fid.readlines())
  
  diffs = difflib.ndiff(lines1, lines2)
  num_diffs = len([d for d in diffs if not d[0] in ['+', '-', '?']])
  return num_diffs / len(lines1)
    


def main():
  flags = parse_flags()
  
  if flags.debug:
    log.setLevel(logging.DEBUG)
  
  df = parse_csv(flags.csv_in)
  assignment_column_number, assignment_name = get_assignment_column_name(df.columns, flags.assignment_name)
  df = df.iloc[:, np.r_[:5, assignment_column_number]]
  
  #temp_dir = os.path.expanduser("~/scratch/grading")
  #os.chdir(temp_dir)
  try:
    shutil.copytree(flags.path_to_files, os.path.abspath("./submissions"))
  except FileExistsError:
    pass
  print(f"curr: {os.path.abspath(os.curdir)}")
  
  
  submissions = get_student_files(os.path.abspath("./submissions"))
  
  if not flags.confusion_only:
    image = build_docker_image(github_repo=flags.github_repo)
    
    if os.path.exists("feedback"): shutil.rmtree("feedback")
    os.mkdir("feedback")
    
    for (i, (student, student_id)) in enumerate(sorted(submissions.keys())):
      log.debug(f"Testing {student}")
      
      # Clean up previous code
      if os.path.exists("student_code"): shutil.rmtree("student_code")
      os.mkdir("student_code")
      
      # Copy the student code to the staging directory
      for file_extension in submissions[(student, student_id)].keys():
        shutil.copy(
          f"./submissions/{submissions[(student, student_id)][file_extension]}",
          f"./student_code/student_code{file_extension}"
        )
      log.debug(f"contents: {os.listdir('./student_code')}")
      
      # Define a comparison function to allow us to pick either the best or worst outcome
      def is_better(score1, score2):
        log.debug(f"is_better({score1}, {score2})")
        if flags.use_max:
          return score2 < score1
        return score1 < score2
      
      # Run docker by passing in files
      if flags.use_max:
        curr_results = {"score" : float('-inf'), "build_logs" : None}
      else:
        curr_results = {"score" : float('+inf'), "build_logs" : None}
      for tag_to_test in flags.tags:
        # worst_results = {"score" : float('inf')}
        for i in range(flags.num_repeats):
          new_results = run_docker_with_archive(image, os.path.abspath("./student_code"), tag_to_test, flags.assignment)
          if is_better(new_results['score'], curr_results['score']):
            log.debug(f"Updating to use new results: {new_results}")
            curr_results = new_results
      curr_results['score'] = max([curr_results['score'], 0])
      print(f"{i} : {student} : {curr_results['score']}")
      write_feedback(student, curr_results)
      student_index = df.index[df['ID'] == int(student_id)]
      df.loc[student_index, assignment_name] = curr_results['score']
      if flags.debug:
        break
    df.to_csv("scores.csv", index=False)
  
  log.debug(f"submissions: {submissions.keys()}")
  submissions_to_compare = sorted([(k[0], submissions[k]['.c']) for k in submissions.keys() if '.c' in submissions[k]])
  df_similarity = pd.DataFrame(columns=[name for (name, _) in submissions_to_compare])
  print(df_similarity)
  
  df_similarity = pd.DataFrame.from_dict({
    name1 : {
      name2 : calc_similarity(os.path.join("./submissions/", sub1), os.path.join("./submissions/", sub2))
      for (name2, sub2) in submissions_to_compare
    }
    for name1, sub1 in submissions_to_compare
  })
  
  print(df_similarity)
  
  # The next line can be expanded
  # What we want is the top right to be the most similar
  # So we pick an arbitrary name, then we want to pick the most similar that hasn't yet been picked
  # Which might be a pain in the ass lol
  # Basically, it's going to be a sort with a lambda that has a set inside of it that is tracking waht's already been added
  # And then rotating them around.
  # There's gotta be a better way...
  # 1. Find the row with the lowest value, use it as a basis
  # 2. find next lowest and repeat
  #df_similarity = df_similarity.sort_values(by=[df_similarity.columns[0]])
  
  similarity_array = df_similarity.to_numpy()
  min_val = similarity_array.min()
  max_val = similarity_array.max()
  similarity_array = (similarity_array - min_val) / max_val
  
  df_similarity = 1 - ((df_similarity - min_val) / max_val)
  
  plt.imshow(similarity_array, cmap='hot')
  plt.show()
  
  values = {}
  for row in df_similarity.index.values:
    for col in df_similarity.columns.values:
      if (row == col): continue
      if (col, row) in values: continue
      values[(row, col)] = df_similarity.loc[row][col]
  
  for names in sorted(values.keys(), key=(lambda n: values[n]), reverse=True):
    if values[names] >= flags.threshold:
      print(f"{names} : {values[names]: 0.3f}")
  
  
  return


if __name__ == "__main__":
  main()