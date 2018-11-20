# Licensed under a 3-clause BSD style license - see LICENSE.rst
from setuptools import setup

from hopper import __version__

try:
     from testr.setup_helper import cmdclass
except ImportError:
     cmdclass = {}

setup(name='hopper',
      author='Tom Aldcroft',
      description='Load checking package',
      author_email='taldcroft@cfa.harvard.edu',
      version=__version__,
      zip_safe=False,
      packages=['hopper'],
      cmdclass=cmdclass,
      )
