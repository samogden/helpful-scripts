#!env python
import argparse
import collections
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
from typing import Dict

import docker
import pandas
import numpy as np
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

logging.basicConfig()
logging.getLogger().setLevel(logging.WARN)

client = docker.from_env()

def parse_flags():
  parser = argparse.ArgumentParser()
  parser.add_argument("--csv_in", default="/Users/ssogden/scratch/csT334/2023-09-29T2137_Grades-CST334-M_01-02_FA23.csv")
  parser.add_argument("--path_to_files", default="/Users/ssogden/scratch/csT334/submissions")
  parser.add_argument("--assignment_name", default="PA1 - Intro to C and Processes (code)")
  parser.add_argument("--num_repeats", default=3)
  parser.add_argument("--tag", default=["main"], action="append", dest="tags")
  parser.add_argument("--assignment", default="PA1")
  parser.add_argument("--confusion_only", action="store_true")
  
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
    logging.debug(f"f: {f}")
    if "student_code" not in f:
      continue
    student_name = f.split("_")[0]
    student_name_id = f.split("_")[1] if "LATE" not in f else f.split("_")[2]
    extension = pathlib.Path(f).suffix
    submission_files[(student_name, student_name_id)][extension] = f
  return submission_files


def build_docker_image():
  
  docker_file = io.BytesIO("""
  FROM samogden/csumb:cst334
  RUN git clone https://github.com/samogden/CST334-assignments.git /tmp/grading
  WORKDIR /tmp/grading/CST334-assignments
  CMD ["/bin/bash"]
  """.encode())
  
  image, logs = client.images.build(
    fileobj=docker_file,
    tag="grading",
    pull=True,
    nocache=True
  )
  logging.debug(logs)
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
    logging.debug(output.decode())
    exit_code, output = container.exec_run(f"tree /tmp/grading/programming-assignments/{programming_assignment}/")
    logging.debug(output.decode())
    
    
    run_str = f"""
      bash -c '
        git checkout {tag_to_test};
        cd /tmp/grading/programming-assignments/{programming_assignment} ;
        timeout 30   python ../../helpers/grader.py --output /tmp/results.json ;
      '
      """
    logging.debug(f"run_str: {run_str}")
    exit_code, output = container.exec_run(run_str)
    try:
      bits, stats = container.get_archive("/tmp/results.json")
    except docker.errors.NotFound:
      return { "score" : 0.0, "build_logs" : [output]}
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
  
  logging.debug(f"results: {results}")
  
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
  return random.random()
  return 1

def main():
  flags = parse_flags()
  
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
    image = build_docker_image()
    
    if os.path.exists("feedback"): shutil.rmtree("feedback")
    os.mkdir("feedback")
    
    for (i, (student, student_id)) in enumerate(sorted(submissions.keys())):
      logging.debug(f"Testing {student}")
      
      # Clean up previous code
      if os.path.exists("student_code"): shutil.rmtree("student_code")
      os.mkdir("student_code")
      
      # Copy the student code to the staging directory
      for file_extension in submissions[(student, student_id)].keys():
        shutil.copy(
          f"./submissions/{submissions[(student, student_id)][file_extension]}",
          f"./student_code/student_code{file_extension}"
        )
      logging.debug(f"contents: {os.listdir('./student_code')}")
      
      # Run docker by passing in files
      best_results = {"score" : float('-inf')}
      for tag_to_test in flags.tags:
        logging.info(f"tag: {tag_to_test}")
        worst_results = {"score" : float('inf')}
        for i in range(flags.num_repeats):
          logging.info(f"i: {i}")
          results = run_docker_with_archive(image, os.path.abspath("./student_code"), tag_to_test, flags.assignment)
          logging.info(f"score: {results['score']}")
          if results["score"] < worst_results["score"]:
            worst_results = results
        if worst_results["score"] > best_results["score"]:
          best_results = worst_results
      
      print(f"{i} : {student} : {best_results['score']}")
      write_feedback(student, best_results)
      student_index = df.index[df['ID'] == int(student_id)]
      df.loc[student_index, assignment_name] = best_results['score']
  
    df.to_csv("scores.csv", index=False)
  
  
  submissions_to_compare = sorted([(k[0], submissions[k]['.c']) for k in submissions.keys()])
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
  
  plt.imshow(df_similarity.to_numpy(), cmap='hot')
  plt.show()
  
  return


if __name__ == "__main__":
  main()