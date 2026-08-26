# ATS provider read-only qualification

Status: public mechanical candidate. It is not a production-qualified application lane.

This slice establishes public, de-umbilicalized ATS provider mechanics without importing private application
facts, bundles, targets, answers, credentials, databases, or operator paths. Greenhouse is the only executable
provider and its only transition is read-only observation. Lever and Ashby are static mapping-only providers.
Workday is an inactive static mapping. No provider grants fill, upload, or submit authority.

## Authority and primitive map

The provider adapter does not define another model-facing grammar, tree walker, matcher, or action primitive.
Every provider compiles the same terminal transition:

| Provider transition | Existing public authority |
|---|---|
| `ui_action({"op":"observe"})` | `consultation_v2.supervised_ui_contract.build_live_ui_action_schema` |
| Read the active document tree | `consultation_v2.tree.find_elements` |
| Match exact form anchors | `consultation_v2.snapshot.matches_spec` |
| Stabilize the projection | provider-owned `invalidate_reacquire`, two consecutive equal projection digests |
| End the transaction | terminal read-only result; `next_mutation_authorized=false` |

The adapter projects only provider ID, provider digest, route grammar ID, hashed application identity, exact
anchor IDs, required-control role/state, opaque references, combo geometry classification, sample receipts,
and digests. Dynamic accessible names and field values remain outside the public/model result.

## Provider matrix

| Provider | Public spec | Executable now | Mutation authority |
|---|---|---:|---|
| Greenhouse | `consultation_v2/ats/providers/greenhouse.yaml` | Read-only qualification candidate | None |
| Lever | `consultation_v2/ats/providers/lever.yaml` | No; mapping only | None |
| Ashby | `consultation_v2/ats/providers/ashby.yaml` | No; mapping only | None |
| Workday | `consultation_v2/ats/providers/workday.yaml` | No; inactive mapping | None |

## Greenhouse canary

The private application service owns target selection, deduplication, account facts, artifacts, leases, and the
database. Hands receives none of those values. Before launch, the private parent must bind one exact display and
Firefox process to one newly selected Greenhouse identity and record that application and submit counts are
unchanged.

The process environment must explicitly contain the display and its AT-SPI bus. The one-run opaque-reference
secret is injected through the environment and must not be a user/model argument:

```bash
DISPLAY=:N \
AT_SPI_BUS_ADDRESS='<display-owned bus>' \
ATS_FIREFOX_PID='<display-owned Firefox PID>' \
ATS_READ_ONLY_LEASE_SECRET='<64 lowercase hex characters>' \
python3 scripts/run_ats_read_only_qualification.py --provider greenhouse
```

The runner performs no navigation, focus, click, key, write, upload, submit, file, clipboard, or database action.
It requires exactly one route-bound active Greenhouse document, exact unique form anchors, at least one exact
AT-SPI-required control, and two consecutive equal projections. It emits one compact terminal JSON result to
stdout. The private parent stores and binds that result to its frozen transaction.

Acceptance for this slice is:

1. exact Greenhouse route and application-identity digest;
2. exact form anchors with no duplicate or missing anchor;
3. a non-empty required-field projection with no dynamic field names or values;
4. two stable read-only samples with successful cache invalidation and reacquisition;
5. every combo outside the active document is retained as a scroll frontier with refusal
   `combo_rect_outside_document_rect`;
6. no field operation and `fill=false`, `upload=false`, `submit=false`;
7. the private parent reads back unchanged application and submit counts; and
8. the display/turn lease closes without another UI mutation.

Any route mismatch, extra matching document, missing/duplicate anchor, absent required field, invalid document
extent, refresh failure, unstable projection, or unexpected provider state terminates the run. There is no
fallback, retry, alternate selector, or mutation recovery.

## Promotion order

Merge and deploy the exact public commit, run one real Greenhouse read-only canary, and preserve its terminal
receipt before discussing field fill. Fill requires its own reviewed non-submit effect authority and production
qualification. Submit requires a further separately frozen outward authority plus exact external-confirmation
and private database readback. Lever and Ashby repeat the read-only qualification independently. Workday remains
inactive until its account and route surface has its own current evidence.

## Mechanical gate

```bash
python3 consultation_v2/validators/validate_ats_provider_read_only.py
```

The gate proves four strict public specs, Greenhouse-only execution, zero UI-mutation calls in the new slice,
route rejection cases, required-field privacy, combo containment/refusal/frontier behavior, and byte identity of
the existing shared primitives, supervised-seat P0 implementation, and five chat policies.
