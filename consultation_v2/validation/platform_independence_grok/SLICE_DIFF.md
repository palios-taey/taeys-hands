# Grok Package Slice Diff

Pinned implementation commit: `81d3d921`.
Observed diff range: `81d3d921^..81d3d921`.

## Commit Summary
```text
81d3d921 Extract Grok platform package
 create mode 100644 consultation_v2/platforms/grok/driver.py
 rename consultation_v2/platforms/{ => grok}/grok.yaml (100%)
 create mode 100644 consultation_v2/platforms/grok/monitor.py
```

## Name Status
```text
M	consultation_v2/drivers/__init__.py
M	consultation_v2/drivers/grok.py
M	consultation_v2/orchestrator.py
A	consultation_v2/platforms/grok/driver.py
R100	consultation_v2/platforms/grok.yaml	consultation_v2/platforms/grok/grok.yaml
A	consultation_v2/platforms/grok/monitor.py
M	consultation_v2/validators/lint_consultation_v2_contract.py
M	consultation_v2/validators/lint_exact_match.py
M	consultation_v2/validators/lint_no_yaml_silent_fallbacks.py
M	consultation_v2/yaml_contract.py
```

## Diffstat
```text
consultation_v2/drivers/__init__.py                |    2 +-
 consultation_v2/drivers/grok.py                    |  987 +----
 consultation_v2/orchestrator.py                    |    2 +-
 consultation_v2/platforms/grok/driver.py           | 3802 ++++++++++++++++++++
 consultation_v2/platforms/{ => grok}/grok.yaml     |    0
 consultation_v2/platforms/grok/monitor.py          |   99 +
 .../validators/lint_consultation_v2_contract.py    |    2 +-
 consultation_v2/validators/lint_exact_match.py     |    4 +-
 .../validators/lint_no_yaml_silent_fallbacks.py    |    2 +-
 consultation_v2/yaml_contract.py                   |    3 +
 10 files changed, 3913 insertions(+), 990 deletions(-)
```

## Slice Summary
- `consultation_v2/platforms/grok/driver.py` is the canonical Grok driver package file (3802 lines). It contains the package-local lifecycle base at `consultation_v2/platforms/grok/driver.py:38` and Grok implementation at `consultation_v2/platforms/grok/driver.py:2851`.
- `consultation_v2/platforms/grok/monitor.py` owns Grok completion detection at `consultation_v2/platforms/grok/monitor.py:48`.
- `consultation_v2/platforms/grok/grok.yaml` is the package-owned YAML; `platform_yaml_path` resolves package YAML first at `consultation_v2/yaml_contract.py:243`.
- `consultation_v2/drivers/grok.py` is reduced to a compatibility import at `consultation_v2/drivers/grok.py:3` so the old path no longer carries a second implementation.
- `consultation_v2/orchestrator.py` and `consultation_v2/drivers/__init__.py` import the package-owned Grok driver at `consultation_v2/orchestrator.py:35` and `consultation_v2/drivers/__init__.py:5`.
- The validator default target discovery now uses recursive YAML discovery so package-owned YAML is included by `--all` gates.
