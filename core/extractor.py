class ExtractorRegistry:
    def extract(self, platform, worker_fn):
        return worker_fn({"cmd": "extract"})
