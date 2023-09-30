#!env python
import argparse
import collections
import io
import json
import logging
import os
import pathlib
import shutil
import tarfile
import tempfile
from typing import Dict

import docker
import pandas

logging.basicConfig()
logging.getLogger().setLevel(logging.WARN)

client = docker.from_env()

def parse_flags():
  parser = argparse.ArgumentParser()
  parser.add_argument("--csv_in", default="/Users/ssogden/scratch/csT334/2023-09-29T2137_Grades-CST334-M_01-02_FA23.csv")
  parser.add_argument("--path_to_files", default="/Users/ssogden/scratch/csT334/submissions")
  parser.add_argument("--assignment_name", default="PA1 - Intro to C and Processes (code)")
  return parser.parse_args()

def parse_csv(path_to_csv):
  df = pandas.read_csv(path_to_csv)
  df = df.iloc[:,:6]
  print(df)
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

def run_docker_with_archive(image, student_files_dir):


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
  container.put_archive("/tmp/grading/programming-assignments/PA1/src", tarstream)
  
  exit_code, output = container.exec_run("ls -l /tmp/grading/programming-assignments/PA1/")
  logging.debug(output.decode())
  exit_code, output = container.exec_run("tree /tmp/grading/programming-assignments/PA1/")
  logging.debug(output.decode())
  
  exit_code, output = container.exec_run(
    """
    bash -c '
      cd /tmp/grading/programming-assignments/PA1
      timeout 10 python ../../helpers/grader.py --output /tmp/results.json
    '
    """
  )
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

def main():
  args = parse_flags()
  
  df = parse_csv(args.csv_in)
  assignment_name = df.columns[-1]
  
  #temp_dir = tempfile.TemporaryDirectory()
  temp_dir = os.path.expanduser("~/scratch/grading")
  os.chdir(temp_dir)
  try:
    shutil.copytree(args.path_to_files, os.path.abspath("./submissions"))
  except FileExistsError:
    pass
  print(f"curr: {os.path.abspath(os.curdir)}")
  
  image = build_docker_image()
  
  if os.path.exists("feedback"): shutil.rmtree("feedback")
  os.mkdir("feedback")
  
  submissions = get_student_files(os.path.abspath("./submissions"))
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
    results = run_docker_with_archive(image, os.path.abspath("./student_code"))
    print(f"{i} : {student} : {results['score']}")
    write_feedback(student, results)
    student_index = df.index[df['ID'] == int(student_id)]
    df.loc[student_index, assignment_name] = results['score']
  df.to_csv("scores.csv")







if __name__ == "__main__":
  main()