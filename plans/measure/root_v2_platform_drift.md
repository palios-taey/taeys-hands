# Root vs consultation_v2 Platform Drift Inventory

Timestamp: 2026-06-14

This is a measurement pass for `task-30f63bec` on the `taeys-hands` repo.
It inventories the current drift between the root `platforms/*.yaml` tree and
the isolated `consultation_v2/platforms/*.yaml` tree.

## Baseline Summary

| Platform | Differing `element_map` rows | Notes |
|---|---:|---|
| ChatGPT | 35 | Large divergence across composer, model, attach, and extract surfaces. |
| Claude | 24 | Effort/menu and attach surfaces differ materially. |
| Gemini | 25 | Mode picker and tool surfaces diverge. |
| Grok | 21 | Model / attach / send surfaces diverge. |
| Perplexity | 48 | Largest drift surface; direct DR path and source/connector panels diverge. |

## Drift Breakdown

The actionable split is:

| Platform | Root-only keys | Shared keys with changed values | V2-only keys |
|---|---:|---:|---:|
| ChatGPT | 5 | 17 | 13 |
| Claude | 2 | 7 | 15 |
| Gemini | 5 | 13 | 7 |
| Grok | 5 | 4 | 12 |
| Perplexity | 6 | 7 | 35 |

Interpretation:

- Root-only keys are the clearest “legacy surface” candidates.
- Shared keys with changed values are the highest-risk drift candidates because the symbolic contract still exists but the live meaning changed.
- V2-only keys are usually intentional contract additions, but they still matter if the root path is expected to remain source-compatible.

## High-Signal Key Diffs

Directional split for the exact `tree.element_map` rows that differ between the
root and `consultation_v2` trees:

### ChatGPT

- Root-only (5):
  - `model_auto`
  - `thinking_pro_button`
  - `tool_google_drive`
  - `tool_quizzes`
  - `tool_study`
- Shared keys with changed values (17):
  - `extended_pro`
  - `input`
  - `model_configure`
  - `model_instant`
  - `model_pro`
  - `model_thinking`
  - `pro_indicator`
  - `stop_button`
  - `temporary_chat`
  - `thinking_extended`
  - `thinking_standard`
  - `tool_agent_mode`
  - `tool_deep_research`
  - `tool_github`
  - `tool_gmail`
  - `tool_more`
  - `tool_web_search`
- V2-only (13):
  - `dictation`
  - `github_chip`
  - `github_configure_repos`
  - `github_repo_item`
  - `github_repo_selector`
  - `github_search_repos`
  - `model_extra_high`
  - `model_high`
  - `model_medium`
  - `tool_create_image`
  - `tool_create_task`
  - `tool_finances`
  - `tool_openai_platform`

### Claude

- Root-only (2):
  - `model_effort_high`
  - `scroll_to_bottom`
- Shared keys with changed values (7):
  - `copy_button`
  - `git_connector_item`
  - `model_opus`
  - `model_selector`
  - `prompt_tab`
  - `stop_button`
  - `toggle_menu`
- V2-only (15):
  - `add_connectors`
  - `add_to_project`
  - `effort_extra`
  - `effort_high_default`
  - `effort_low`
  - `effort_max`
  - `effort_medium`
  - `effort_menu`
  - `model_fable`
  - `skills`
  - `take_screenshot`
  - `thinking_toggle`
  - `tool_research`
  - `tool_web_search`
  - `use_style`

### Gemini

- Root-only (5):
  - `deep_think_active`
  - `deep_think_item`
  - `model_3_5_thinking`
  - `more_tools_button`
  - `upload_tools`
- Shared keys with changed values (13):
  - `add_from_drive_item`
  - `copy_button`
  - `input`
  - `input_alt`
  - `mode_fast`
  - `mode_picker`
  - `mode_pro`
  - `mode_thinking`
  - `share_export`
  - `tool_canvas`
  - `tool_create_image`
  - `tool_deep_research`
  - `upload_files_item`
- V2-only (7):
  - `more_tools`
  - `new_chat`
  - `tool_create_music`
  - `tool_create_video`
  - `tool_deep_think`
  - `tool_deselect_deep_think`
  - `tool_guided_learning`

### Grok

- Root-only (5):
  - `edit_button`
  - `read_aloud`
  - `scroll_down`
  - `start_thread`
  - `thought_indicator`
- Shared keys with changed values (4):
  - `dictation`
  - `input`
  - `stop_button`
  - `voice_mode`
- V2-only (12):
  - `connectors_item`
  - `history`
  - `model_auto`
  - `model_expert`
  - `model_fast`
  - `model_heavy`
  - `recent_item`
  - `remove_attachment`
  - `search`
  - `send_button`
  - `skills_item`
  - `uploaded_file_chip`

### Perplexity

- Root-only (6):
  - `answer_mode_tabs`
  - `answer_tab`
  - `deep_research_radio`
  - `images_tab`
  - `links_tab`
  - `search_toggle`
- Shared keys with changed values (7):
  - `copy_contents_button`
  - `git_connector_item`
  - `incognito`
  - `input`
  - `stop_button`
  - `submit_button`
  - `upload_files_item`
- V2-only (35):
  - `add_files_from_cloud`
  - `attach_more_trigger`
  - `clear_search`
  - `computer_dropdown`
  - `computer_ready`
  - `connector_asana`
  - `connector_box`
  - `connector_circleback`
  - `connector_cloudinary`
  - `connector_confluence`
  - `copy_query_button`
  - `create_files_indicator`
  - `deep_research`
  - `deep_research_item`
  - `deep_research_toggle`
  - `learn_step_indicator`
  - `manage_connectors`
  - `mode_create_files`
  - `mode_learn`
  - `model_council_indicator`
  - `new_thread`
  - `scheduled`
  - `search_sources`
  - `source_academic`
  - `source_blockscout`
  - `source_github`
  - `source_gmail`
  - `source_google_drive`
  - `source_health`
  - `source_social`
  - `source_web`
  - `spaces_item`
  - `suggestion_tab_for_you`
  - `suggestion_tabs`
  - `tool_model_council`

## Observations

- The two trees are not in simple parity. They encode different interaction
  contracts and validation shapes.
- The current measurement is a baseline only. It does not imply that every
  difference is a bug.
- The remaining work for this task is to separate intentional contract
  divergence from accidental drift, then close the accidental part file by file.

## Verification

- Compared root and V2 YAMLs for all five chat platforms.
- Computed per-platform `tree.element_map` drift counts.
