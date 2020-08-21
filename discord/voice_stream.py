class VoiceStreamFactory:
    def create_voice_stream(self):
        pass


class VoiceStream:
    def __init__(self, user_id: int):
        self.user_id = user_id

    def on_start(self):
        pass

    def on_data(self, data):
        pass

    def on_end(self):
        pass
