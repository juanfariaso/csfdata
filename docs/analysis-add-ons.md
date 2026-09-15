# Analysis Add-Ons

The lightweight `csfdata` package does not include science-analysis
dependencies. Optional packages can register themselves as analysis add-ons.

Use the shared discovery interface after installing an add-on:

```python
from csfdata import analysis

analysis.available()
addon = analysis.load("csfdata_analysis")
```

The `csfdata_analysis` repository is the initial add-on skeleton. Its actual
analysis products and public interface have not been defined yet. In
particular, AMUSE will be added there only if a specific product needs it.

