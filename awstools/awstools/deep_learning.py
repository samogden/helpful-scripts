#!env python

import logging
logging.basicConfig()
log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)

import collections
import pprint

import pandas as pd
import numpy as np

import lambda_tools

LAMBDA_COST_MODIFIER = 1.0

def deploy_model(model_name, memory_size=1024, *args, **kwargs):
  with open("templates/lambda_interpreter.py") as fid:
    handler_str = fid.read()
  function_name = lambda_tools.create_function_inference(
    function_name_base=f"{model_name}",
    model_name=model_name,
    handler_str=handler_str,
    MemorySize=memory_size,
    env={"MODEL_NAME" : model_name},
    *args, **kwargs
  )
  log.debug(function_name)
  return function_name


class LambdaModel(object):
  def __init__(self, model_name, *args, **kwargs):
    self.lambda_client = lambda_tools.get_client()
    self.model_name = model_name
    self.function_name = deploy_model(model_name, client=self.lambda_client)
  
  def take_measurement(self, burned_requests=3):
    for _ in range(burned_requests):
      lambda_tools.invoke_function(self.function_name, client=self.lambda_client)
    response_dict = lambda_tools.invoke_function(self.function_name, client=self.lambda_client)
    if "errorMessage" in response_dict["parsed_response"]:
      return {
        'client_latency' : response_dict["measured_latency"],
        'execution_latency' : response_dict["parsed_log"]["Duration"],
        'billed_latency' : float("+inf"),
        'memory_size' : response_dict["parsed_log"]["Memory Size"],
        'memory_used' : response_dict["parsed_log"]["Max Memory Used"],
      } 
    return {
      'client_latency' : response_dict["measured_latency"],
      'execution_latency' : response_dict["parsed_log"]["Duration"],
      'billed_latency' : response_dict["parsed_log"]["Billed Duration"],
      'memory_size' : response_dict["parsed_log"]["Memory Size"],
      'memory_used' : response_dict["parsed_log"]["Max Memory Used"],
    }
      
  def change_memory(self, new_memory):
    lambda_tools.update_function_memory(self.function_name, new_memory, client=self.lambda_client)
  
  def cleanup(self):
    lambda_tools.delete_function(self.function_name)
  
  def _round_of_measurement(self, mem_sample_point, num_measurements):
    self.change_memory(mem_sample_point)
    costs = []
    for i in range(num_measurements):
      measurement = self.take_measurement(burned_requests=(3 if i==0 else 0))
      cost = LAMBDA_COST_MODIFIER * measurement["memory_size"] * measurement["billed_latency"]
      costs.append(cost)
    return costs
  
  def find_minimum_cost_grid(self, min_memory=512, max_memory=5*1024, step_size=128, num_measurements=100):
    costs = collections.defaultdict(list)
    for mem_sample_point in range(min_memory, max_memory+1, step_size):
      costs[mem_sample_point] = self._round_of_measurement(mem_sample_point, num_measurements)
      log.debug(f"{self.model_name}-{mem_sample_point} : {(sum(costs[mem_sample_point]) / len(costs[mem_sample_point])):0.3f}")
    df = pd.DataFrame(costs)
    self.minimum_cost_memory = df.mean().idxmin()
    return self.minimum_cost_memory
  
  
  def find_minimum_cost_convex(self, min_memory=128, max_memory=10240, num_measurements=100):
    step_size = int((max_memory - min_memory) / 2)
    costs = collections.defaultdict(list)
    #costs[min_memory] = _round_of_measurement(min_memory, num_measurements)
    #costs[max_memory] = _round_of_measurement(max_memory, num_measurements)
    
    prev_size = max_memory
    prev_measurement = self._round_of_measurement(prev_size, num_measurements)
    log.debug(f"{self.model_name} : {prev_size} -> {np.mean(prev_measurement)}")
    costs[prev_size] = prev_measurement
    going_up = False
    while step_size > 1:
      curr_size = (prev_size + step_size) if going_up else (prev_size - step_size)
      curr_measurements = self._round_of_measurement(curr_size, num_measurements)
      costs[curr_size] = curr_measurements
      
      log.debug(f"{self.model_name} : {curr_size} -> {np.mean(curr_measurements)}")
      # Compare the previous cost against this cost
      if np.mean(prev_measurement) > np.mean(curr_measurements):
        # If this cost is lower, then we should keep going in the same direction
        going_up = going_up
      else:
        # Otherwise we should flip and check the other way
        going_up = (not going_up)
      
      prev_size = curr_size
      prev_measurement = curr_measurements
      step_size = int(step_size/2)
    df = pd.DataFrame(costs)
    self.minimum_cost_memory = df.mean().idxmin()
    return self.minimum_cost_memory
    


if __name__ == '__main__':
  models = [
    "efficientnetb0",
    "efficientnetb7",
    "nasnetmobile",
    "resnet152v2",
    "vgg19"
  ]
  cost_points = {}
  for model_name in models:
    try:
      model = LambdaModel(model_name)
      minimum_cost_memory = model.find_minimum_cost_convex()
      cost_points[model.model_name] = minimum_cost_memory
      print(f"{model.model_name} : {model.minimum_cost_memory}")
    finally:
      model.cleanup()
  
  for model, memory in cost_points.items():
    print(f"{model} : {memory}")
  
  