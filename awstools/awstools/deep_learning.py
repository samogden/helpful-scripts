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
