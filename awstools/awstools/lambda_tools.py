#!env python

import logging
logging.basicConfig()
log = logging.getLogger(__name__)

import time
import base64
import io
import zipfile
import os
import pathlib
import tempfile
import json

import boto3

#from . import logs
import logs
import s3_tools

def get_client():
  return boto3.client('lambda')

def invoke_function(function_name, *args, **kwargs):
  if "client" in kwargs:
    client = kwargs["client"]
  else:
    client = get_client()
    
  ts = time.time()
  response = client.invoke(
    FunctionName=function_name,
    LogType="Tail", # includes log in response
    Payload=b'' if "payload" not in kwargs else kwargs["payload"],
  )
  te = time.time()
  
  payload = response["Payload"].read().decode('utf-8')
  log = base64.b64decode(response["LogResult"]).decode('utf-8')
  
  #log.debug(response["Payload"].read().decode('utf-8'))
  return {
    'response' : payload,
    'parsed_response' : json.loads(payload),
    'log' : log,
    'parsed_log' : logs.parse_log_event(log),
    'measured_latency' : (te - ts)
  }

def create_function(function_name, handler_str=None, *args, **kwargs):
  log.info(f"Creating function {function_name}")
  if "client" in kwargs:
    client = kwargs["client"]
  else:
    client = get_client()
  
  function_name = f"{function_name}-{int(time.time())}"
  
  # Base for serving deep learning models, which this is mostly used for
  zip_base = s3_tools.get_file_obj("layercake.config", "python38_tflite.zip")
  
  with zipfile.ZipFile(zip_base, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
    info = zipfile.ZipInfo("lambda_function.py")
    info.external_attr = 0o777 << 16 # give full access to included file
    
    # Write out handler to a file so we can get the permissions right
    temp = tempfile.NamedTemporaryFile(mode='w', delete=False)
    temp.write(handler_str)
    temp.flush()
    os.chmod(temp.name, 0o777)
    zip_file.write(temp.name, "lambda_function.py")
      
  zip_base.seek(0)
      
  response = client.create_function(
    FunctionName=f"{function_name}",
    Role="arn:aws:iam::253976646984:role/vgg19-threadtest-9-10240-dev-us-east-1-lambdaRole",
    Code={'ZipFile' : zip_base.read()},
    Runtime="python3.8",
    Handler="lambda_function.predict",
    Timeout=60 if "timeout" not in kwargs else kwargs["timeout"],
    MemorySize=10240 if "memory_size" not in kwargs else kwargs["memory_size"],
    Environment={} if "env" not in kwargs else {'Variables' : kwargs["env"]}
  )
  
  log.debug(response)
  log.info(f"Created as {function_name}")
  return function_name

def get_function_memory(function_name, *args, **kwargs):
  log.info(f"Getting memory: {function_name}")
  if "client" in kwargs:
    client = kwargs["client"]
  else:
    client = get_client()
  
  response = client.get_function_configuration(
    FunctionName=function_name,  
  )
  
  return response["MemorySize"]
  
def update_function_memory(function_name, new_memory, *args, **kwargs):
  log.info(f"Updating memory: {function_name} -> {new_memory}")
  if "client" in kwargs:
    client = kwargs["client"]
  else:
    client = get_client()
  
  client.update_function_configuration(
    FunctionName=function_name,
    MemorySize=new_memory  
  )

def delete_function(function_name, *args, **kwargs):
  if "client" in kwargs:
    client = kwargs["client"]
  else:
    client = get_client()
  client.delete_function(
    FunctionName=function_name,
  )


if __name__ == '__main__':
  log.setLevel(logging.DEBUG)
