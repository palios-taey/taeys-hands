# Greenhouse One-Action ATS Lane

## Status and boundary

This is the public deterministic execution boundary for Greenhouse-hosted job
forms on `boards.greenhouse.io` and `job-boards.greenhouse.io`. It does not
claim support for branded domains, other ATS providers, or production
qualification.

The lane is autonomous through exact employer confirmation. There is no
routine human review or approval queue. A caller supplies one private frozen
action, the runner performs at most one mapped UI mutation, Hands proves the
YAML-owned postcondition with consecutive fresh observations, and a durable
receipt authorizes the next action. Submit is one action and succeeds only
after the employer confirmation route and exact confirmation anchor are both
stable.

The lane stops on only these public codes:

- `exact_postcondition_failure`
- `unmapped_ui_or_question`
- `missing_truthful_applicant_data`
- `policy_or_authority_boundary`
- `side_effect_uncertainty`

A terminal result never authorizes another mutation. An incomplete prior
`execution_started` receipt is also terminal because its side effect is
uncertain.

## Public authorities

The mutable public authorities are:

- `consultation_v2/ats/providers/greenhouse_one_action.yaml` for exact action
  roles, upload slots, Submit names, barriers, native chooser contract, and
  confirmation anchors;
- `consultation_v2/ats/providers/greenhouse.yaml` for exact route grammars;
- `consultation_v2/ats/greenhouse_one_action.py` for deterministic projection,
  binding, one-action execution, barriers, and receipts;
- `consultation_v2/native_dialog_snapshot.py` for the sole native-dialog tree
  traversal;
- existing `consultation_v2.tree`, `consultation_v2.interact`,
  `consultation_v2.input`, and
  `ConsultationRuntime.scroll_element_into_view` primitives.

No applicant answers, artifact paths, account data, or receipt payloads belong
in Git.

## Shared mechanics and provider-specific boundary

The lane reuses the public Hands primitives for focus, text entry, mapped
pointer activation, exact AT-SPI click, cleared key presses, scrolling,
provider document reacquisition, menu-item observation, native-dialog
observation, and durable receipt storage. It does not duplicate any of those
mechanics.

Two blocks remain Greenhouse-specific by design:

- the form projection, because ATS controls, required-state evidence, upload
  slots, and completion digest are not represented by the chat-platform tree;
- the postcondition predicate, because the existing stable-snapshot helpers
  compare chat-platform projections rather than the exact control, value
  digest, choice state, artifact proof, or employer-confirmation state owned
  by this ATS contract.

Both blocks consume the existing canonical AT-SPI traversal and interaction
primitives. Neither is a second walker, locator grammar, or mutation path.

## Exact lifecycle

The autonomous caller advances this sequence using the action card returned by
the prior receipt:

1. `observe_form`
2. `focus`, then `fill`, for each exact empty editable control
3. `scroll_combo` when an exact combo rectangle is outside the active document
4. `open_combo` only when its live rectangle is contained by the active
   document
5. `select_option` from a newly observed options revision
6. `activate_choice` for an exact mapped checkbox, radio button, or toggle
7. `open_upload`
8. `chooser_location`
9. `chooser_select_all`
10. `chooser_type_path`
11. `chooser_confirm`
12. `submit`

Each invocation performs zero or one UI mutation. Multiple read-only samples
inside the postcondition barrier do not add mutation authority. Dynamic
dropdown options are never reused from an earlier menu observation.

Every successful non-submit action also emits one bounded
`ats_greenhouse_next_action_surface_v1` capsule. It contains only the exact
current refs, public control labels, declared operations, completion booleans,
surface revision, and source-surface digest needed to derive one next action.
Applicant values, value digests, selected semantic values, native paths, and
native text are absent. Options are included only from the freshly observed
options surface. For the exact Greenhouse `Country` combo, each public rendered
option name must satisfy the YAML-owned `country_calling_code_suffix_v1`
contract. The capsule preserves that rendered name for exact selection and
separately exposes its public country-name `semantic_token`; every other combo
continues to expose no semantic token.

After exact Country-option activation, the postcondition passes only when the
collapsed exact bound combo exposes the exact rendered option name in its
canonical `semantic_values`. An empty canonical value fails closed even if a
nearby node exposes the option's calling-code suffix. A calling code is not a
unique country proof and never authorizes the next mutation.

The native chooser is also one action per call. The ATS lane supplies its
validated YAML contract, one exact Firefox object, and the exact configured
Firefox PID to the shared native-dialog walker. It does not implement another
tree traversal.

## Environment contract

Every invocation requires explicit values:

```text
DISPLAY
AT_SPI_BUS_ADDRESS
ATS_FIREFOX_PID
ATS_ONE_ACTION_LEASE_SECRET
ATS_ONE_ACTION_RECEIPT_ROOT
ATS_HANDS_COMMIT
ATS_PRESENCE_INCARNATION_ID
ATS_HANDS_INCARNATION_ID
```

`ATS_ONE_ACTION_LEASE_SECRET` is 64 lowercase hexadecimal characters.
`ATS_ONE_ACTION_RECEIPT_ROOT` is an existing worker-owned directory with mode
`0700`, outside every public repository. The frozen transaction is an absolute
worker-owned regular JSON file with mode `0400` or `0600`, also outside the
public repository.

## Frozen action envelope

Every private action uses exactly this envelope:

```json
{
  "schema": "ats_greenhouse_frozen_action_v1",
  "provider": "greenhouse",
  "transaction_id": "00000000-0000-4000-8000-000000000000",
  "action_id": "00000000-0000-4000-8000-000000000001",
  "application_identity_sha256": "<64 lowercase hex>",
  "expected_prior_event_hash": null,
  "action": {
    "kind": "observe_form"
  }
}
```

After the first action, `expected_prior_event_hash` is the exact
`receipt_event_hash` returned by the preceding action. Reusing an action ID,
using a stale receipt hash, or continuing a terminal transaction is refused.

Fill actions carry the private value and its SHA-256. Artifact actions carry
the private absolute path, basename, slot, and content SHA-256. Durable receipt
payloads record only value length/digest and artifact basename/slot/digest.
Native location-entry text is likewise reduced to length and digest.

Submit actions additionally carry:

```json
{
  "kind": "submit",
  "ref": "<exact current Submit ref>",
  "revision": "<exact current form revision>",
  "precondition": {
    "required_controls_complete": true,
    "truth_attested": true,
    "complete_form_sha256": "<exact digest returned by observe_form>",
    "truth_attestation_sha256": "<private attestation digest>",
    "artifacts": [
      {
        "slot": "resume",
        "name": "<basename>",
        "path": "<private absolute path>",
        "sha256": "<content digest>"
      }
    ]
  }
}
```

Before Submit, Hands re-observes the exact application identity, compares the
live complete-form digest, verifies required controls, and proves every bound
artifact under its exact YAML-owned upload slot. After the single Submit click,
the transaction becomes successful only when the exact
`hosted_confirmation` route and one exact visible YAML-owned confirmation
anchor stabilize.

Submit success additionally emits one
`ats_greenhouse_employer_confirmation_v1` capsule. It binds the provider and
application identity, exact hosted-confirmation route match, exact single
YAML-owned visible anchor, one stable surface revision, and the count and digest
of its consecutive matched barrier samples. The durable event is written from
that evidence first. Only then is its event hash added as `receipt_sha256` to
the returned capsule, so the receipt binding is exact and non-self-referential.

## Invocation

```python
import os
import subprocess

action_fd = os.open(
    private_action_path,
    os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
)
try:
    subprocess.run(
        [
            python,
            'scripts/run_ats_greenhouse_one_action.py',
            '--transaction-fd',
            str(action_fd),
            '--expected-transaction-sha256',
            validated_action_sha256,
        ],
        pass_fds=(action_fd,),
        check=True,
    )
finally:
    os.close(action_fd)
```

The production Presence adapter opens and validates the private frozen action
before presenting its opaque card, retains that exact descriptor through the
single `operate` call, and passes only the descriptor plus its digest to Hands.
The runner has no pathname input or fallback. Replacing or unlinking the source
pathname cannot substitute a different action after the card is issued.

Exit status is zero only for a passed action and postcondition receipt. A
refusal or terminal result exits one.

## Mechanical gates

```bash
python3 consultation_v2/validators/validate_ats_greenhouse_one_action.py
python3 consultation_v2/validators/validate_ats_provider_read_only.py
python3 consultation_v2/validators/lint_consultation_v2_contract.py --all
python3 consultation_v2/validators/lint_no_yaml_silent_fallbacks.py --all
python3 consultation_v2/validators/lint_platform_independence.py --all
git diff --check
```

These gates prove public contract shape and regression containment. They are
not a production claim. Production qualification requires a separate,
authorized run using private truthful applicant data and real employer
confirmation evidence.
