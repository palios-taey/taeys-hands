# Claude Package Manual Leaf-Cleanliness Audit

Task gate: do not rely on isolation lint alone for pre-retire leaf classification.

Command:

```text
rg -n "\bif\b.*platform|platform.*\bif\b|elif .*platform|match .*platform|case .*platform" consultation_v2/clipboard.py consultation_v2/tree.py consultation_v2/yaml_contract.py consultation_v2/types.py consultation_v2/notify.py consultation_v2/identity.py consultation_v2/storage_policy.py consultation_v2/ingest.py consultation_v2/stop_conditions.py consultation_v2/input.py consultation_v2/atspi.py consultation_v2/platforms/_routing_core.py
```

Observed raw hits:

```text
consultation_v2/yaml_contract.py:242:    if platform not in KNOWN_PLATFORMS:
consultation_v2/yaml_contract.py:1001:    if platform not in CHAT_PLATFORMS:
consultation_v2/tree.py:444:    if platform_doc:
consultation_v2/tree.py:456:    if platform_doc:
consultation_v2/tree.py:463:    if platform_doc:
consultation_v2/tree.py:469:    if platform_doc:
consultation_v2/tree.py:481:    if platform_doc:
```

Classification:

| File | Hit(s) | Classification |
| --- | --- | --- |
| `consultation_v2/yaml_contract.py` | `KNOWN_PLATFORMS`, `CHAT_PLATFORMS` membership checks | Declared registry/data validation carve-out under `PLATFORM_INDEPENDENCE_SPEC.md` section 4; no per-platform behavior branch. |
| `consultation_v2/tree.py` | `if platform_doc` object-presence checks | Document-presence checks on the caller-provided AT-SPI document object; no branch on platform identity or platform policy. |
| `consultation_v2/platforms/_routing_core.py` | No raw platform-branch hits | Mechanical routing helper parameterized by package-owned `RouteSpec`; no per-platform branch in the shared core. |

Conclusion: no manual evidence of platform-conditional behavior in the leaf set for this slice.
