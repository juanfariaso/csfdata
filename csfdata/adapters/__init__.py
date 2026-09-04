"""
Class adapters for importing simulations. 
Each module is dedicated to a simulation code and should have a standard
format.\n
- These importers should be read only.
- Other modules will take care of the syncyng. The job of these modules is to
  translate them.
"""

from csfdata.adapters.dcaf import DcafAdapter

__all__ = ["DcafAdapter"]
