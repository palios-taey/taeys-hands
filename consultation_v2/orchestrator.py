from __future__ import annotations

from consultation_v2.types import ConsultationRequest, ConsultationResult
from consultation_v2.drivers.chatgpt import ChatGPTConsultationDriver
from consultation_v2.drivers.claude import ClaudeConsultationDriver
from consultation_v2.drivers.gemini import GeminiConsultationDriver
from consultation_v2.drivers.grok import GrokConsultationDriver
from consultation_v2.drivers.perplexity import PerplexityConsultationDriver


_REGISTRY = {
    'chatgpt': ChatGPTConsultationDriver,
    'claude': ClaudeConsultationDriver,
    'gemini': GeminiConsultationDriver,
    'grok': GrokConsultationDriver,
    'perplexity': PerplexityConsultationDriver,
}


def run_consultation(request: ConsultationRequest) -> ConsultationResult:
    if request.platform not in _REGISTRY:
        raise ValueError(f'Unsupported platform: {request.platform}')
    driver = _REGISTRY[request.platform]()
    return driver.run(request)
