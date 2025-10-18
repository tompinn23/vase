from distutils.core import setup

import py2exe

setup(console=['vase/main.py'],
      options={
          "py2exe": {
              "packages": ["vase.data"],  # include the package
              "bundle_files": 1,  # optional
          }
      },
      data_files=[("vase/data", ["vase/data/ships.json"])])