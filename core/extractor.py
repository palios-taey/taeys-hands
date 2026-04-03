class ExtractorRegistry:
    STRATEGIES = {
        "chatgpt": "chatgpt_last_assistant_copy",
        "claude": "artifact_copy_then_message_copy",
        "gemini": "last_copy",
        "grok": "last_copy",
        "perplexity": "copy_contents_for_dr_else_last_copy",
    }

    def get_strategy(self, platform):
        return self.STRATEGIES.get(platform, "last_copy")

    def extract(self, platform, worker_fn):
        strategy = self.get_strategy(platform)
        return worker_fn({"cmd": "extract", "strategy": strategy})
