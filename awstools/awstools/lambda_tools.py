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
import tempfile
import json

import boto3

#from . import logs
from . import logs
from . import s3_tools

def get_client():
  return boto3.client('lambda')

def create_function(function_name, deployment_package_obj, *args, **kwargs):
  log.info(f"Creating function {function_name}")
  if "client" in kwargs:
    client = kwargs["client"]
  else:
    client = get_client()
      
  response = client.create_function(
    FunctionName=f"{function_name}",
    Role="arn:aws:iam::253976646984:role/vgg19-threadtest-9-10240-dev-us-east-1-lambdaRole",
    Code={'ZipFile' : deployment_package_obj.read()},
    Runtime="python3.8",
    Handler="lambda_function.predict",
    Timeout=60 if "timeout" not in kwargs else kwargs["timeout"],
    MemorySize=10240 if "memory_size" not in kwargs else kwargs["memory_size"],
    Environment={} if "env" not in kwargs else {'Variables' : kwargs["env"]}
  )
  
  log.debug(response)
  log.info(f"Created as {function_name}")
  return function_name

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
  log_info = base64.b64decode(response["LogResult"]).decode('utf-8')
  
  #log.debug(response["Payload"].read().decode('utf-8'))
  return {
    'response' : payload,
    'parsed_response' : json.loads(payload),
    'log' : log_info,
    'parsed_log' : logs.parse_log_event(log_info),
    'measured_latency' : (te - ts)
  }

def get_function_inference(model_name, *args, **kwargs):
  log.info(f"Getting function: {model_name}")
  if "client" in kwargs:
    client = kwargs["client"]
  else:
    client = get_client()
  
  log.debug(f"Checking for function: {model_name}")
  functions_available = client.list_functions()['Functions']
  for existing_function in functions_available:
    existing_function_name = existing_function["FunctionName"]
    log.debug(f"Checking {existing_function_name} : {model_name in existing_function_name}")
    if model_name in existing_function_name:
      log.debug(f"Using existing function: {existing_function_name}")
      return existing_function_name
      #return client.get_function(FunctionName=existing_function_name)
  return create_function_inference(model_name=model_name, client=client)

def create_function_inference(*args, **kwargs):
  
  if "function_name" in kwargs and kwargs["function_name"] is not None:
    function_name = kwargs["function_name"]
    del kwargs["function_name"]
  elif "model_name" in kwargs and kwargs["model_name"] is not None:
    function_name = f"{kwargs['model_name']}-{int(time.time())}"
  else:
    function_name = f"function-{time.time()}"
  
  if "env" not in kwargs:
    kwargs["env"] = {"MODEL_NAME" : kwargs["model_name"] }
    
  
  # Base for serving deep learning models, which this is mostly used for
  zip_base_obj = s3_tools.get_file_obj("layercake.config", "python38_tflite.zip")
  interpreter_script_obj = s3_tools.get_file_obj("layercake.config", "lambda_interpreter.py")
  
  with zipfile.ZipFile(zip_base_obj, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
    
    # Write out handler to a file so we can get the permissions right
    temp = tempfile.NamedTemporaryFile(mode='w', delete=False)
    temp.write(interpreter_script_obj.read().decode('UTF-8'))
    temp.flush()
    os.chmod(temp.name, 0o777)
    zip_file.write(temp.name, "lambda_function.py")
      
  zip_base_obj.seek(0)
  
  return create_function(function_name, zip_base_obj, *args, **kwargs)

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
