
# Clustered Star Formation Database


This repo meant to manage a simulations of star cluster formation made with D-CAF. However it may manage other star cluster simulations in the future.


The idea here is that this repo can copy an existing grid of simulations and integrate it on a standalone server. Later we can use this repository to query simulations of a given model, initial conditions etc.

The goal is also to have a lite version of the database that can be stored locally, which will contain only the artifacts derivations of a simulation, such as lagrangian radii evolution, bound fraction evolution, etc.


# Install

After you clone, from inside the `csfdata` directory:
```
pip install .
```

# Related repositories:

csfdata : This repository. The responsability of this repository is to handle the data transfer and organization.


There are two more repositories that should be installed in top of this, for other related resposabilities.
  - [csfdata_analysis](https://github.com/juanfariaso/csfdata_analysis) : It handles the interface between the raw data and analysis tools. It is also useful for exploring and working with the catalogues.
  - csfdata_scheduler: (to be completed) This repository will be able to submit jobs and run simulations on a proposed grid of parameters. Simulations organized with this will be much easier to import into the database.

# Documentation:
- [csfdata Documentation](https://juanfariaso.github.io/csfdata/)
- [csfdata_analysis Documentation](https://juanfariaso.github.io/csfdata_analysis/)

## Disclaimer
For efficiency and ease of maintenance, I developed this project with assistance from Codex/ChatGPT. All scientific decisions and architectural design are my own, but not all code and documentation were written by me. On this repository I want to prioritize clean, easy-to-use code and well-documented decisions, for anyone to use.
