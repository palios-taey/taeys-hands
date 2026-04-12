from consultation_v2.drivers.base import YamlDrivenConsultationDriver


class ChatGPTConsultationDriver(YamlDrivenConsultationDriver):
    platform = "chatgpt"
