# THE RULE — enforced in every function in this file:
from consultation_v2.drivers.base import YamlDrivenConsultationDriver


class ChatGPTConsultationDriver(YamlDrivenConsultationDriver):
    platform = "chatgpt"
