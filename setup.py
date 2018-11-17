# Licensed under a 3-clause BSD style license - see LICENSE.rst
from setuptools import setup

try:
     from testr.setup_helper import cmdclass
except ImportError:
     cmdclass = {}

setup(name='hopper',
      author='Tom Aldcroft',
      description='Load checking package',
      author_email='taldcroft@cfa.harvard.edu',
      version='0.1',
      zip_safe=False,
      packages=['hopper'],
      cmdclass=cmdclass,
      )
