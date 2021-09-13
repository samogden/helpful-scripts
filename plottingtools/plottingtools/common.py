#!env python

from math import sqrt

import numpy as np

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.lines as mlines

from matplotlib.patches import Patch
from matplotlib import cm


# Gets a default set of markers.  May need to add more markers as needed
def getMarkers():
    return ['+', 'o', 'x', '^', 'v', 's']

# Gets a range of BW colors ranging from dark to light but never including pure black or white
def getBWColors(num_fields, stringify=True):
    if stringify:
        return ["%s" % c for c in getBWColors(num_fields, False)]
    return (1-(np.arange(0,num_fields+1)/float(num_fields+1)))[::-1][:-1]

# Sets Parameters based on "width" of plot.
#   If "width" is set to "markdown" then a reasonably sized PNG file is generated
#   If "width" is set to a float in [0.5, 0.3, 0.25] then a PDF file of this fraction of the page width will be generated
def setRCParams(width=0.5, height=0.5, *args, **kwargs):
    params = {
        "savefig.format"    : 'pdf',
        'text.usetex'       : 'false'
    }
    
    if width == "markdown":
        params['figure.figsize'] = [6.6, 3.0]
        params['font.size'] = (16)
        params['savefig.format'] = 'png'
    elif width == 0.5:
        params['figure.figsize'] = [3.3, 1.5]
        params['font.size'] = ('%s' % (8*(3/4.)))
    elif width == 0.3:
        params['figure.figsize'] = [2.2, 1.5]
        params['font.size'] = ('%s' % (8*(2/3.)))
    elif width == 0.25:
        params['figure.figsize'] = [2.0, 2.0]
        params['font.size'] = ('%s' % (8*(2./2.)))
    else:
        params['figure.figsize'] = [3.3, 1.5]
    
    if height == 0.5:
        pass
    elif height == 1.0:
        x, y = tuple(params['figure.figsize'])
        
        params['figure.figsize'] = [x, y*2]
    
        
    matplotlib.rcParams.update(params)

def loadRCParamsFile(path_to_file="matplotlibrc"):
    with open(path_to_file) as fid:
        param_lines = [s.strip() for s in fid.readlines()]

    params = {}
    for line in param_lines:
        if line.strip() == '':
            continue
        if line.strip().startswith('#'):
            continue

        parts = line.split(':')
        key = parts[0].strip()
        value = ':'.join(parts[1:]).strip()
        params[key] = value
    matplotlib.rcParams.update(params)


