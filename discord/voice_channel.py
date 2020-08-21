from typing import Optional, List

from .voice_stream import VoiceStream, VoiceStreamFactory


class VoiceChannel:
    MAX_SILENT_FRAMES = 5

    def __init__(self, ssrc: int, voice_stream_factory: VoiceStreamFactory):
        self.ssrc: int = ssrc
        self.voice_stream_factory: VoiceStreamFactory = self.voice_stream_factory

        self.user_id: Optional[int] = None
        self.voice_stream: Optional[VoiceStream] = None
        self._silence_counter: int = 0

        self._buffered_data: List[any] = []

    def __del__(self):
        pass

    def set_user(self, user_id: int):
        self.user_id = user_id
        self.voice_stream = self.voice_stream_factory.create_voice_stream()
        self.voice_stream.on_start()
        for data in self._buffered_data:
            self.voice_stream.on_data(data)

    def on_data(self, data: bytes, sequence: int, timestamp: int):
        if self.voice_stream is None:
            self._buffered_data.append(data)
            return

        # Check for explicit silence frames
        if len(data) == 3:
            self._silence_counter += 1
            if self._silence_counter >= VoiceChannel.MAX_SILENT_FRAMES:
                self.voice_stream.on_end()
                self.voice_stream = None
            return

        self.voice_stream.on_data(data)
