"""The checks every pull request to the ChRIS plugin index must pass.

Key components:
    - index: run every check and report what fails.
    - model: read plugin descriptors into typed models.
    - plugins: the rules the plugin schema cannot express.
    - credentials: keep credentials out of the index.
    - pipelines: hold each pipeline to the plugins it is made of.
    - shelves: hold ``shelves.yml`` to the index.
    - style_check: hold this package to the Python style guide.

Typical usage:
    python -m checks.index

Dependencies:
    ``jsonschema`` and ``pyyaml``, as ``pyproject.toml`` lists them.
"""
