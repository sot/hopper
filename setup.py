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
      use_scm_version=True,
      setup_requires=['setuptools_scm', 'setuptools_scm_git_archive'],
      zip_safe=False,
      packages=['hopper'],
      cmdclass=cmdclass,
      )
