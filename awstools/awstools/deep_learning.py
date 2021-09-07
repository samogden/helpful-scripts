#!env python

import logging
logging.basicConfig()
log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)

import lambda_tools

def deploy_model(model_name, memory_size=1024):
  with open("templates/lambda_interpreter.py") as fid:
    handler_str = fid.read()
  function_name = lambda_tools.create_function(
    function_name=f"{model_name}-{memory_size}mb",
    handler_str=handler_str,
    MemorySize=memory_size,
    env={"MODEL_NAME" : model_name}
  )
  log.debug(function_name)
  return function_name



if __name__ == '__main__':
  
  function_name = deploy_model("vgg19")
  log.debug(function_name)
  response = lambda_tools.invoke_function(function_name)
  log.debug(response)
  lambda_tools.update_function_memory(function_name, 128)
  response = lambda_tools.invoke_function(function_name)
  log.debug(response)
  lambda_tools.update_function_memory(function_name, 10240)
  response = lambda_tools.invoke_function(function_name)
  log.debug(response)

exit()

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
  
  lambda_tools.create_function("my_func", handler_str)

exit()