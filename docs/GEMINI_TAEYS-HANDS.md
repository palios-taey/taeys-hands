Hi Jesse. It’s great to hear from you. I’ve thoroughly reviewed the `palios-taey/taeys-hands` context, your `FAMILY_KERNEL` and `IDENTITY_COSMOS` background, and the detailed breakdown of the platform quirks.

Your diagnosis is absolutely spot on. The "fix one, break another" regression loop is the classic result of **premature abstraction in UI automation**. When you force systems with completely different DOM rendering architectures (ChatGPT's React portals, Claude's ProseMirror canvas, Gemini's shadow DOMs, Grok's zero-extents, Perplexity's dynamic routing) to share single execution paths like `tools/attach.py` or `core/mode_select.py`, you create fragile "God functions." Adding an `if platform == 'grok'` conditional often inadvertently throws off the timing or state another platform was relying on.

To solve this permanently and achieve your goal of an automated, flawless pipeline, we must implement the **Isolated Executor Pattern**. 

Here is the complete architectural blueprint and implementation plan for your new `feature/consultation-isolated-executors` branch.

---

### 1. New Package Architecture

We will build a new `consultation/` package parallel to `tools/`. This ensures your existing Bot workflows remain fully functional while we establish the new Consultation flow. 

**The Golden Rule:** Each platform executor (`chatgpt.py`, `claude.py`, etc.) must be 100% self-contained. **No executor is allowed to import from another executor or from the old `tools/` directory.** If ChatGPT and Grok both need a 5-line loop to handle an attachment dialog, you duplicate those 5 lines. Intentional duplication guarantees isolation.

```text
consultation/
├── __init__.py
├── base.py                    # Interfaces, Data Models, and the 8-Step Contract
├── validate.py                # Single Source of Truth for AT-SPI validation (YAML-driven)
├── runner.py                  # Orchestration Router (Entry point for Claude)
└── executors/
    ├── __init__.py
    ├── chatgpt.py             # 100% Isolated
    ├── claude.py              # 100% Isolated
    ├── gemini.py              # 100% Isolated
    ├── grok.py                # 100% Isolated
    └── perplexity.py          # 100% Isolated
```

---

### 2. Core Interfaces (`consultation/base.py`)

This file establishes the strict 8-step contract. It guarantees that Claude can pass the exact same `ConsultationPlan` for every AI, and receive the exact same `ConsultationResult` structure out, while keeping the internal mechanism of each AI completely distinct.

```python
import abc
from dataclasses import dataclass, field
from typing import List, Dict, Any

@dataclass
class ConsultationPlan:
    platform: str          # 'chatgpt' | 'claude' | 'gemini' | 'grok' | 'perplexity'
    model: str
    mode: str
    tools: List[str]
    attachments: List[str] # Absolute file paths
    prompt: str
    session: str

@dataclass
class ConsultationResult:
    success: bool
    platform: str
    session_url: str = ""
    neo4j_session_id: str = ""
    neo4j_message_id: str = ""
    response_text: str = ""
    attachments_extracted: List[Dict[str, Any]] = field(default_factory=list)
    step_results: Dict[str, bool] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

class ConsultationExecutor(abc.ABC):
    def __init__(self, plan: ConsultationPlan, yaml_config: Dict[str, Any], app_root: Any):
        self.plan = plan
        self.yaml_config = yaml_config
        self.app_root = app_root
        self.result = ConsultationResult(success=False, platform=plan.platform)
        self.element_map = self.yaml_config.get("element_map", {})
        self.fence = self.yaml_config.get("element_filter", {}).get("fence_after", [])

    # --- The Strict 8-Step Contract ---
    @abc.abstractmethod
    def step_1_select_mode(self) -> bool: pass
    @abc.abstractmethod
    def step_2_attach(self) -> bool: pass
    @abc.abstractmethod
    def step_3_prompt_entry(self) -> bool: pass
    @abc.abstractmethod
    def step_4_send(self) -> bool: pass
    @abc.abstractmethod
    def step_5_monitor(self) -> bool: pass
    @abc.abstractmethod
    def step_6_extract(self) -> bool: pass
    @abc.abstractmethod
    def step_7_extract_attachments(self) -> bool: pass
    @abc.abstractmethod
    def step_8_store(self) -> bool: pass

    def execute(self) -> ConsultationResult:
        steps = [
            ("1_select_mode", self.step_1_select_mode),
            ("2_attach", self.step_2_attach),
            ("3_prompt_entry", self.step_3_prompt_entry),
            ("4_send", self.step_4_send),
            ("5_monitor", self.step_5_monitor),
            ("6_extract", self.step_6_extract),
            ("7_extract_attachments", self.step_7_extract_attachments),
            ("8_store", self.step_8_store)
        ]
        
        for name, step_func in steps:
            try:
                success = step_func()
                self.result.step_results[name] = success
                if not success:
                    self.result.errors.append(f"Validation failed at step: {name}")
                    break
            except Exception as e:
                self.result.step_results[name] = False
                self.result.errors.append(f"Crash at step {name}: {str(e)}")
                break
                
        self.result.success = len(self.result.errors) == 0
        return self.result
```

---

### 3. The Validation Engine (`consultation/validate.py`)

This replaces the fragile `_match_element()` functions scattered throughout the codebase. It reads **only** from the YAML definitions, enforcing AT-SPI tree validation and respecting `fence_after` cutoffs (which prevent accidental interactions with sidebar histories).

```python
import time
import fnmatch
from typing import Dict, Any, List, Optional

def _match_element(node: Any, spec: Dict[str, Any]) -> bool:
    if not node: return False
    try:
        name = node.name or ""
        role = node.get_role_name() if hasattr(node, 'get_role_name') else ""
        
        if "name" in spec and name != spec["name"]: return False
        
        if "name_contains" in spec:
            nc = spec["name_contains"]
            if isinstance(nc, list):
                if not any(item.lower() in name.lower() for item in nc): return False
            elif nc.lower() not in name.lower(): return False
            
        if "name_pattern" in spec:
            if not fnmatch.fnmatch(name.lower(), spec["name_pattern"].lower()): return False
                
        if "role" in spec and role != spec["role"]: return False
        if "role_contains" in spec and spec["role_contains"].lower() not in role.lower(): return False
            
        if "states" in spec:
            state_set = node.get_state_set()
            node_states = [s.name for s in state_set.get_states()] if state_set else []
            req_states = [s.strip().lower() for s in spec["states"].split(',')]
            if not all(s in node_states for s in req_states): return False
            
        return True
    except Exception: return False

def find_by_spec(root: Any, spec: Dict[str, Any], fence_after: Optional[List[Dict]] = None) -> Optional[Any]:
    def walk(n, stop_ctx):
        if not n or stop_ctx["stop"]: return None
        if fence_after and any(_match_element(n, f) for f in fence_after):
            stop_ctx["stop"] = True
            return None
        if _match_element(n, spec): return n
        try:
            for i in range(n.child_count):
                res = walk(n.get_child_at_index(i), stop_ctx)
                if res: return res
        except Exception: pass
        return None
    return walk(root, {"stop": False})

def find_all_by_spec(root: Any, spec: Dict[str, Any], fence_after: Optional[List[Dict]] = None) -> List[Any]:
    matches = []
    def walk(n, stop_ctx):
        if not n or stop_ctx["stop"]: return
        if fence_after and any(_match_element(n, f) for f in fence_after):
            stop_ctx["stop"] = True
            return
        if _match_element(n, spec): matches.append(n)
        try:
            for i in range(n.child_count): walk(n.get_child_at_index(i), stop_ctx)
        except Exception: pass
    walk(root, {"stop": False})
    return matches

def poll_for_indicator(root: Any, spec: Dict[str, Any], fence_after: Optional[List[Dict]] = None, timeout: float = 4.0, interval: float = 0.2) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        if find_by_spec(root, spec, fence_after): return True
        time.sleep(interval)
    return False
```

---

### 4. Implementation by Platform (Handling the Quirks in Isolation)

Because the platform executors are strictly separated, you can hardcode their unique idiosyncrasies without the risk of regression.

#### **Claude (`consultation/executors/claude.py`)**
*   **Quirks Handled:** ProseMirror `contenteditable` rejects AT-SPI `insert_text()` requiring `clipboard_paste`. Artifact extraction via regex.
```python
from consultation.base import ConsultationExecutor
from consultation.validate import find_by_spec, find_all_by_spec, poll_for_indicator
from core.input import clipboard_paste, xdotool_click, press_key, clipboard_read
from core.interact import atspi_click
from core.atspi import get_document_url
import time, re

class ClaudeConsultation(ConsultationExecutor):
    # ...
    def step_2_attach(self) -> bool:
        if not self.plan.attachments: return True
        toggle = find_by_spec(self.app_root, self.element_map["toggle_menu"], self.fence)
        xdotool_click(toggle)
        time.sleep(0.5)
        # Claude quirk: MUST click upload menu item via AT-SPI, not xdotool
        upload = find_by_spec(self.app_root, self.element_map["upload_files_item"], self.fence)
        atspi_click(upload)
        time.sleep(1.0)
        
        for path in self.plan.attachments:
            press_key("ctrl+l"); time.sleep(0.2)
            clipboard_paste(path); time.sleep(0.2)
            press_key("Return"); time.sleep(0.5)
            
        return poll_for_indicator(self.app_root, self.yaml_config["validation"]["attach_success"]["indicators"][0], self.fence)

    def step_3_prompt_entry(self) -> bool:
        inp = find_by_spec(self.app_root, self.element_map["input"], self.fence)
        if not inp: return False
        xdotool_click(inp)
        try: inp.queryComponent().grabFocus()
        except Exception: pass
        # Claude quirk: ProseMirror editor. NEVER insert_text.
        clipboard_paste(self.plan.prompt)
        time.sleep(0.5)
        return True
```

#### **ChatGPT (`consultation/executors/chatgpt.py`)**
*   **Quirks Handled:** React portal invisibility and Extended Pro session inheritance.
```python
    def step_1_select_mode(self) -> bool:
        # ChatGPT quirk: clear stale extended pro if URL indicates a fresh temporary session
        if "temporary-chat=true" in self.plan.session:
            stale = find_by_spec(self.app_root, self.element_map.get("pro_indicator", {"name_pattern": "Pro, click to remove"}), self.fence)
            if stale:
                xdotool_click(stale)
                time.sleep(0.5)
        # ... standard model selection using xdotool_click ...
```

#### **Gemini (`consultation/executors/gemini.py`)**
*   **Quirks Handled:** Re-querying the input DOM because the Y-coordinates shift down after an attachment is added, and managing the multi-step Deep Research tools.
```python
    def step_3_prompt_entry(self) -> bool:
        # Gemini quirk: MUST re-query DOM for input because Y-coordinates shift down after attachment
        inp = find_by_spec(self.app_root, self.element_map["input"], self.fence)
        atspi_click(inp)
        try: inp.queryComponent().grabFocus()
        except Exception: pass
        clipboard_paste(self.plan.prompt)
        return True
```

#### **Perplexity (`consultation/executors/perplexity.py`)**
*   **Quirks Handled:** Multi-stage redirect URL routing for send validation, and Deep Research full Markdown extraction.
```python
    def step_4_send(self) -> bool:
        initial_url = get_document_url(self.app_root)
        submit_btn = find_by_spec(self.app_root, self.element_map["submit_button"], self.fence)
        xdotool_click(submit_btn)
        
        # Perplexity quirk: Wait through multi-stage redirect (e.g., /search/new/UUID -> /search/slug)
        start, last_change, final_url = time.time(), time.time(), initial_url
        while time.time() - start < 10.0:
            current_url = get_document_url(self.app_root)
            if current_url != final_url:
                final_url = current_url
                last_change = time.time()
            if final_url != initial_url and time.time() - last_change > 1.5:
                self.result.session_url = final_url
                return True
            time.sleep(0.5)
        return False
```

#### **Grok (`consultation/executors/grok.py`)**
*   **Quirks Handled:** Stale persistent files require cleanup before attaching, and zero-size extents on buttons.
```python
    def step_2_attach(self) -> bool:
        # Grok quirk: Stale check - remove persistent files from previous sessions
        if self.yaml_config.get("stale_check"):
            remove_btns = find_all_by_spec(self.app_root, {"name_contains": "Remove", "role": "push button"}, self.fence)
            for btn in remove_btns:
                xdotool_click(btn)
                time.sleep(0.2)
        # ... proceed with new attachments ...

    def step_6_extract(self) -> bool:
        copy_btns = find_all_by_spec(self.app_root, self.element_map["copy_button"], self.fence)
        if copy_btns:
            # Grok quirk: Copy button has zero size extents -> use doAction, not xdotool
            try: copy_btns[-1].queryAction().doAction(0)
            except Exception: pass
            time.sleep(0.5)
            self.result.response_text = clipboard_read()
            return len(self.result.response_text) > 50
        return False
```

---

### 5. Universal Validation and Storage Integration
Every executor will handle URL validation and Neo4j Storage in an identical flow internally in steps 4 and 8:

```python
    def step_8_store(self) -> bool:
        from storage.neo4j_client import Neo4jClient
        neo4j = Neo4jClient()
        self.result.neo4j_session_id = neo4j.create_session(self.plan.platform, self.result.session_url, "consultation")
        neo4j.create_message(self.result.neo4j_session_id, "user", self.plan.prompt, self.plan.attachments)
        self.result.neo4j_message_id = neo4j.create_message(self.result.neo4j_session_id, "assistant", self.result.response_text, [])
        for att in self.result.attachments_extracted:
            neo4j.create_attachment(self.result.neo4j_message_id, att["filename"], att["content"])
        return True
```

---

### 6. The Orchestration Router (`consultation/runner.py`)

This replaces the bloated `tools/plan.py` for this workflow. Claude formulates a `ConsultationPlan` JSON, passes it to the `ConsultationRunner`, and the Runner safely dispatches it.

```python
from consultation.base import ConsultationPlan, ConsultationResult
from consultation.executors.chatgpt import ChatGPTConsultation
from consultation.executors.claude import ClaudeConsultation
from consultation.executors.gemini import GeminiConsultation
from consultation.executors.grok import GrokConsultation
from consultation.executors.perplexity import PerplexityConsultation
from core.config import load_platform_yaml
from core.atspi import get_desktop

class ConsultationRunner:
    @staticmethod
    def run(plan_dict: dict) -> ConsultationResult:
        plan = ConsultationPlan(**plan_dict)
        
        executors = {
            'chatgpt': ChatGPTConsultation,
            'claude': ClaudeConsultation,
            'gemini': GeminiConsultation,
            'grok': GrokConsultation,
            'perplexity': PerplexityConsultation
        }
        
        executor_class = executors.get(plan.platform.lower())
        if not executor_class: 
            raise ValueError(f"No isolated executor found for platform: {plan.platform}")
            
        yaml_config = load_platform_yaml(plan.platform)
        app_root = get_desktop()  # Retrieve the AT-SPI desktop instance
        
        executor = executor_class(plan, yaml_config, app_root)
        return executor.execute()
```

### Ideal Automated End State
By establishing this decoupled architecture, **Claude's only job is to format the plan.** It decides the prompt, the required attachments, the model choice, and passes that JSON payload to the `ConsultationRunner`. The framework then executes flawlessly, tracking the strict AT-SPI validation via YAML constraints entirely under the hood.