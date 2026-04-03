from unittest.mock import mock_open, patch

from core.extractor import ExtractorRegistry
from tools import extract


def test_read_clipboard_uses_explicit_display():
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))

        class Result:
            returncode = 0
            stdout = "copied text"
            stderr = ""

        return Result()

    with patch("tools.extract.subprocess.run", side_effect=fake_run):
        content, tool_name = extract._read_clipboard(display=":9")

    assert content == "copied text"
    assert tool_name == "xclip"
    assert calls[0][0] == ['xclip', '-selection', 'clipboard', '-o']
    assert calls[0][1]["env"]["DISPLAY"] == ":9"


def test_read_clipboard_falls_back_to_xsel():
    def fake_run(cmd, **kwargs):
        raise FileNotFoundError("xclip missing")

    with patch("tools.extract.subprocess.run", side_effect=fake_run):
        content, tool_name = extract._read_clipboard(display=":7")

    assert content is None
    assert tool_name == "xclip"


def test_handle_quick_extract_returns_strategy_and_content():
    copy_button = {'x': 10, 'y': 20, 'name': 'Copy', 'role': 'push button'}

    with patch("tools.extract.inp.switch_to_platform", return_value=True), \
         patch("tools.extract.get_platform_config", return_value={}), \
         patch("tools.extract.inp.press_key"), \
         patch("tools.extract.atspi.find_firefox_for_platform", return_value=object()), \
         patch("tools.extract.atspi.get_platform_document", return_value=object()), \
         patch("tools.extract.atspi.get_document_url", return_value="https://example.test"), \
         patch("tools.extract.find_elements", return_value=[copy_button]), \
         patch("tools.extract._try_perplexity_deep_research_extract", return_value=(None, "not_applicable")), \
         patch("tools.extract._try_claude_artifact_extract", return_value=(None, "not_applicable")), \
         patch("tools.extract._click_and_read_clipboard", return_value=("hello world", "atspi+xclip")), \
         patch("tools.extract._assess_extraction", return_value={"likely_complete": True}), \
         patch("tools.extract.SCREEN_HEIGHT", 1000), \
         patch("tools.extract.auto_ingest", return_value={"ok": True}):
        result = extract.handle_quick_extract("gemini", redis_client=None, display=":4")

    assert result["success"] is True
    assert result["content"] == "hello world"
    assert result["extraction_method"] == "last_copy_button"


def test_handle_quick_extract_bootstraps_display_and_dbus_from_platform():
    copy_button = {'x': 10, 'y': 20, 'name': 'Copy', 'role': 'push button'}

    def fake_read_clipboard(*_args, **kwargs):
        assert extract.os.environ["DISPLAY"] == ":5"
        assert extract.os.environ["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/tmp/a11y-bus"
        assert extract.os.environ["AT_SPI_BUS_ADDRESS"] == "unix:path=/tmp/a11y-bus"
        return "hello world", "atspi+xclip"

    with patch.dict("tools.extract.os.environ", {}, clear=True), \
         patch("tools.extract.get_platform_display", return_value=":5"), \
         patch("tools.extract.get_platform_config", return_value={}), \
         patch("builtins.open", mock_open(read_data="unix:path=/tmp/a11y-bus")), \
         patch("tools.extract.inp.switch_to_platform", return_value=True), \
         patch("tools.extract.atspi.find_firefox_for_platform", return_value=object()), \
         patch("tools.extract.atspi.get_platform_document", return_value=object()), \
         patch("tools.extract.atspi.get_document_url", return_value="https://grok.example"), \
         patch("tools.extract.find_elements", return_value=[copy_button]), \
         patch("tools.extract._try_perplexity_deep_research_extract", return_value=(None, "not_applicable")), \
         patch("tools.extract._try_claude_artifact_extract", return_value=(None, "not_applicable")), \
         patch("tools.extract._click_and_read_clipboard", side_effect=fake_read_clipboard) as read_clipboard, \
         patch("tools.extract._assess_extraction", return_value={"likely_complete": True}), \
         patch("tools.extract.SCREEN_HEIGHT", 1000), \
         patch("tools.extract.auto_ingest", return_value={"ok": True}):
        result = extract.handle_quick_extract("grok", redis_client=None)

    assert result["success"] is True
    assert read_clipboard.call_args.kwargs["display"] == ":5"


def test_extractor_registry_calls_worker_without_strategy():
    registry = ExtractorRegistry()
    calls = []

    result = registry.extract("chatgpt", lambda payload: calls.append(payload) or {"ok": True})

    assert result == {"ok": True}
    assert calls == [{"cmd": "extract"}]


class _FakeRect:
    def __init__(self, x=0, y=0, width=20, height=20):
        self.x = x
        self.y = y
        self.width = width
        self.height = height


class _FakeComponent:
    def __init__(self, rect):
        self._rect = rect

    def get_extents(self, _coord_type):
        return self._rect


class _FakeNode:
    def __init__(self, name="", role="section", attrs=None, children=None, x=0, y=0):
        self._name = name
        self._role = role
        self._attrs = attrs or {}
        self._children = children or []
        self._component = _FakeComponent(_FakeRect(x=x, y=y))

    def get_name(self):
        return self._name

    def get_role_name(self):
        return self._role

    def get_child_count(self):
        return len(self._children)

    def get_child_at_index(self, index):
        return self._children[index]

    def get_component_iface(self):
        return self._component

    def get_attributes(self):
        return [f"{key}:{value}" for key, value in self._attrs.items()]


def test_select_chatgpt_last_assistant_copy_button_uses_last_assistant_group():
    first_button = {
        "name": "Copy response",
        "role": "push button",
        "x": 10,
        "y": 100,
        "atspi_obj": object(),
    }
    second_button = {
        "name": "Copy response",
        "role": "push button",
        "x": 10,
        "y": 300,
        "atspi_obj": object(),
    }
    user_button = {
        "name": "Copy response",
        "role": "push button",
        "x": 10,
        "y": 500,
        "atspi_obj": object(),
    }

    user_group = _FakeNode(
        name="user message",
        role="section",
        attrs={"xml-roles": "user"},
        x=0,
        y=500,
    )
    assistant_one = _FakeNode(
        name="assistant one",
        role="section",
        attrs={"xml-roles": "assistant"},
        x=0,
        y=100,
    )
    assistant_two = _FakeNode(
        name="assistant two",
        role="section",
        attrs={"xml-roles": "assistant"},
        x=0,
        y=300,
    )
    conversation = _FakeNode(
        name="Conversation",
        role="section",
        children=[assistant_one, assistant_two, user_group],
        x=0,
        y=0,
    )
    document = _FakeNode(name="Document", role="document web", children=[conversation])

    def fake_find_elements(scope, max_depth=25, exclude_landmarks=None, fence_after=None):
        if scope is assistant_one:
            return [first_button]
        if scope is assistant_two:
            return [second_button]
        if scope is user_group:
            return [user_button]
        return []

    with patch("tools.extract.find_elements", side_effect=fake_find_elements):
        button, meta = extract._select_chatgpt_last_assistant_copy_button(document)

    assert button == second_button
    assert meta["assistant_groups_found"] == 2
