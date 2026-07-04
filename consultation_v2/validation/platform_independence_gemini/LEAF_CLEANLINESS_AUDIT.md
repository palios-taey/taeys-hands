# Gemini Package Manual Leaf-Cleanliness Audit

Pinned source SHA: `ddc55dc89538bffddd9622ae03103cbcc48a133a`.

This audit is separate from `lint_platform_independence.py --all`, because the task requires manual leaf cleanliness evidence before shared-base retirement.

## Command

```text
python3 - <<'SMOKE'
import ast
from pathlib import Path
from consultation_v2.validators import lint_platform_independence as lint
root = Path('.')
platform_names = {'chatgpt','claude','gemini','grok','perplexity'}
findings = []
for rel in lint.LEAF_MODULES:
    path = root / rel
    if not path.exists():
        continue
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.IfExp, ast.Match)):
            text = ast.unparse(node.test if isinstance(node, (ast.If, ast.IfExp)) else node.subject)
            lowered = text.lower()
            if 'platform' in lowered or any(name in lowered for name in platform_names):
                findings.append((str(rel), getattr(node, 'lineno', 1), text))
print('leaf_count', sum(1 for rel in lint.LEAF_MODULES if (root / rel).exists()))
print('routing_core_in_leaf_modules', Path('consultation_v2/platforms/_routing_core.py') in lint.LEAF_MODULES)
print('platform_branch_findings', len(findings))
for item in findings:
    print(item)
SMOKE
```

## Observed Output

```text
leaf_count 12
routing_core_in_leaf_modules True
platform_branch_findings 8
('consultation_v2/tree.py', 444, 'platform_doc')
('consultation_v2/tree.py', 456, 'platform_doc')
('consultation_v2/tree.py', 463, 'platform_doc')
('consultation_v2/tree.py', 469, 'platform_doc')
('consultation_v2/tree.py', 481, 'platform_doc')
('consultation_v2/yaml_contract.py', 242, 'platform not in KNOWN_PLATFORMS')
('consultation_v2/yaml_contract.py', 1001, 'platform not in CHAT_PLATFORMS')
('consultation_v2/ingest.py', 116, 'mapped not in _ALLOWED_ISMA_PLATFORMS')
```

## Classification

| File:line | Observed branch | Classification |
| --- | --- | --- |
| `consultation_v2/tree.py:444` | `if platform_doc` | Mechanical object-presence branch for a document subtree parameter; not platform identity. |
| `consultation_v2/tree.py:456` | `if platform_doc` | Mechanical object-presence branch for a document subtree parameter; not platform identity. |
| `consultation_v2/tree.py:463` | `if platform_doc` | Mechanical object-presence branch for a document subtree parameter; comment mentions Gemini as historical evidence only, no platform branch. |
| `consultation_v2/tree.py:469` | `if platform_doc` | Mechanical object-presence branch for a document subtree parameter; not platform identity. |
| `consultation_v2/tree.py:481` | `if platform_doc` | Mechanical object-presence branch for a document subtree parameter; not platform identity. |
| `consultation_v2/yaml_contract.py:242` | `platform not in KNOWN_PLATFORMS` | Declared-registry guard explicitly allowed by `PLATFORM_INDEPENDENCE_SPEC.md` section 4. |
| `consultation_v2/yaml_contract.py:1001` | `platform not in CHAT_PLATFORMS` | Declared-registry guard explicitly allowed by `PLATFORM_INDEPENDENCE_SPEC.md` section 4. |
| `consultation_v2/ingest.py:116` | `mapped not in _ALLOWED_ISMA_PLATFORMS` | Declared-registry/data validation guard explicitly allowed by `PLATFORM_INDEPENDENCE_SPEC.md` section 4. |

Observed conclusion: no per-platform conditional behavior branch was found in the leaf set; `_routing_core.py` is included in the scanned leaf modules.
