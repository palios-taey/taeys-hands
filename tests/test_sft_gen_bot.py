import agents.sft_gen_bot as sft_gen_bot


class _FakeInput:
    def focus_firefox(self):
        return True

    def press_key(self, _key):
        return True

    def click_at(self, _x, _y):
        return True


class _FakeBot:
    def __init__(self):
        self.inp = _FakeInput()


def test_handle_perplexity_post_send_deep_research_noop_for_other_platforms():
    bot = _FakeBot()

    assert sft_gen_bot._handle_perplexity_post_send_deep_research('claude', bot) is False


def test_handle_perplexity_post_send_deep_research_clicks_start(monkeypatch):
    bot = _FakeBot()
    clicked = []

    monkeypatch.setattr(sft_gen_bot.time, 'sleep', lambda _seconds: None)
    monkeypatch.setattr(sft_gen_bot.time, 'time', lambda: 100.0)
    monkeypatch.setattr(
        sft_gen_bot,
        '_inspect_platform_controls',
        lambda platform, _bot, scroll_bottom=True: [
            {'name': 'Start research', 'role': 'push button', 'x': 10, 'y': 20}
        ],
    )
    monkeypatch.setattr(
        sft_gen_bot,
        '_click_control',
        lambda platform, control, _bot: clicked.append((platform, control['name'])) or True,
    )

    assert sft_gen_bot._handle_perplexity_post_send_deep_research('perplexity', bot) is True
    assert clicked == [('perplexity', 'Start research')]


def test_handle_perplexity_post_send_deep_research_clears_active_mode(monkeypatch):
    bot = _FakeBot()
    disabled = []
    time_values = iter([0.0, 11.0, 12.0, 13.0, 14.0])
    controls = [
        {'name': 'Deep Research', 'role': 'check menu item', 'states': ['checked']},
    ]

    monkeypatch.setattr(sft_gen_bot.time, 'sleep', lambda _seconds: None)
    monkeypatch.setattr(sft_gen_bot.time, 'time', lambda: next(time_values))
    monkeypatch.setattr(
        sft_gen_bot,
        '_inspect_platform_controls',
        lambda platform, _bot, scroll_bottom=True: controls,
    )
    monkeypatch.setattr(
        sft_gen_bot,
        '_disable_perplexity_deep_research',
        lambda platform, _bot, seen_controls: disabled.append((platform, seen_controls)) or True,
    )

    assert sft_gen_bot._handle_perplexity_post_send_deep_research('perplexity', bot) is True
    assert disabled == [('perplexity', controls)]
