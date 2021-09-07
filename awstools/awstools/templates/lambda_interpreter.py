import json
import collections
import time
import os

import functools

import numpy as np

import tflite_runtime.interpreter as tflite

import boto3

import io
import tempfile

s3 = boto3.client('s3')

model_file = f"{os.environ['MODEL_NAME']}.tflite"

temp_file = tempfile.NamedTemporaryFile()
data_stream = io.BytesIO()

s3.download_fileobj('layercake.models', 
                      model_file,
                      data_stream)
data_stream.seek(0)

interpreter = tflite.Interpreter(model_content=data_stream.getvalue(), num_threads=6)
interpreter.allocate_tensors()

was_cold = True

def add_metadata(func):
  
  @functools.wraps(func)
  def wrapper(*args, **kwargs):
    global was_cold
    ts = time.time()
    response = func(*args, **kwargs)
    response["execution_time_ms"] = 1000*(time.time() - ts)
    response["was_cold"] = was_cold
    was_cold = False
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
    "statusCode" : 200,
    "model_file" : model_file,
    "body" : json.dumps(
      outputs
    )
  }
  
  return response