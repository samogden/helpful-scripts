#!env python

import logging
logging.basicConfig()
log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)

import time
import base64
import io
import zipfile
import os
import pathlib

import boto3

#from . import logs
import logs

def get_client():
  return boto3.client('lambda')

def invoke_function(lambda_client, function_name):
  ts = time.time()
  response = lambda_client.invoke(
    FunctionName=function_name,
    LogType="Tail" # includes log in response
  )
  te = time.time()
  
  parsed_log = logs.parse_log_event(base64.b64decode(response["LogResult"]).decode('utf-8'))
  
  return (te - ts), parsed_log

def create_function(handler_str=None):
  client = get_client()
  
  
  zip_buffer = io.BytesIO()
  with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
    #for file_name, data in [('1.txt', io.BytesIO(b'111')), ('2.txt', io.BytesIO(b'222'))]:
    #  zip_file.writestr(file_name, data.getvalue())
    if handler_str is None:
      zip_file.write("tests/simple_handler.py")
    else:
      zip_file.writestr("lambda_function.py", handler_str)
    
    zipdir("package", zip_file)
    zip_file.extractall("./extract_dir")
  zip_buffer.seek(0)
      
  response = client.create_function(
    FunctionName=f"function-{int(time.time())}",
    Role="arn:aws:iam::253976646984:role/vgg19-threadtest-9-10240-dev-us-east-1-lambdaRole",
    Code={'ZipFile' : zip_buffer.read()},
    Runtime="python3.8",
    Handler="lambda_function.predict",
  )
  
  log.debug(response)

## Utility Functions ##

def zipdir(path, ziph):
  # ziph is zipfile handle
  for root, dirs, files in os.walk(path):
    p = pathlib.Path(root)
    #for file in files:
    #  log.debug(f"file: {os.path.join(pathlib.Path(*p.parts[1:]), file)}")
    for file in files:
      ziph.write(os.path.join(root, file), 
                 os.path.join(pathlib.Path(*p.parts[1:]), file))
                                     
#######################



if __name__ == '__main__':
  
  handler_str = """
import json
import collections
import time

import functools

import numpy as np

import tflite_runtime.interpreter as tflite

import boto3

import io
import tempfile

s3 = boto3.client('s3')

model_file = "efficientnetb0.tflite"

temp_file = tempfile.NamedTemporaryFile()
data_stream = io.BytesIO()

s3.download_fileobj('layercake.models', 
                      model_file,
                      data_stream)
data_stream.seek(0)

interpreter = tflite.Interpreter(model_content=data_stream.getvalue(), num_threads=10)
interpreter.allocate_tensors()

times_used = 0


def add_metadata(func):
  
  @functools.wraps(func)
  def wrapper(*args, **kwargs):
    global times_used
    ts = time.time()
    response = func(*args, **kwargs)
    response["execution_time_ms"] = 1000*(time.time() - ts)
    response["times_used"] = times_used
    times_used += 1
    return response
  return wrapper
  
  
@add_metadata
def predict(event, context):
  
  for i, input_detail in enumerate(interpreter.get_input_details()):
    interpreter.set_tensor(
      input_detail['index'], 
      np.array(
        np.random.random_sample(
          input_detail["shape"]
        )
        , dtype=input_detail["dtype"]
      )
    )
  
  sTime = time.time()
  interpreter.invoke()
  print(time.time()-sTime)
  
  outputs = {}
  for i, output_detail in enumerate(interpreter.get_output_details()):
    outputs[i] = f"{interpreter.get_tensor(output_detail['index'])}"
    
  response = {
    "statusCode": 200,
    "body": json.dumps(
      outputs
    )
  }
  
  return response
"""
  
  create_function(handler_str)
