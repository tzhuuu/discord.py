from typing import Optional, List, Tuple

from .opus import Decoder
from .sliding_window import SlidingWindow
from .voice_stream import VoiceStream, VoiceStreamFactory


class VoiceChannel:
    MIN_SILENT_FRAMES = 5
    SILENCE_BYTES = bytearray(b'\xf8\xff\xfe')

    def __init__(self, ssrc: int, voice_stream_factory: Optional[VoiceStreamFactory]):
        self.ssrc: int = ssrc
        self.voice_stream_factory = voice_stream_factory

        self.user_id: Optional[int] = None
        self.voice_stream: Optional[VoiceStream] = None
        self._silence_counter: int = 0

        self._buffered_data: List[any] = []

        self._sliding_window = SlidingWindow(32, 2147483647, self._invoke_voice_stream)

        self._decoder = Decoder()

    def __del__(self):
        self._sliding_window.flush()

    def _invoke_voice_stream(self, data: Tuple[int, Optional[bytes]]):
        if self.voice_stream is not None:
            # Decode the opus audio data
            timestamp, opus_audio = data
            pcm_audio = self._decoder.decode(opus_audio)
            self.voice_stream.on_data((timestamp, pcm_audio))

    def set_user(self, user_id: int):
        self.user_id = user_id
        self.maybe_init_voice_stream()

    def set_voice_stream_factory(self, factory: VoiceStreamFactory):
        self.voice_stream_factory = factory
        self.maybe_init_voice_stream()

    def _create_voice_stream(self):
        assert self.voice_stream is None
        self._decoder.reset()
        self.voice_stream = self.voice_stream_factory.create_voice_stream(self.user_id)

    def maybe_init_voice_stream(self):
        # Need the user and voice stream to be set
        if self.user_id is not None and self.voice_stream_factory is not None:
            self._create_voice_stream()
            self.voice_stream.on_start()
            for data in self._buffered_data:
                self.voice_stream.on_data(data)
            self._buffered_data.clear()

    def on_data(self, opus_audio_data: bytes, sequence: int, timestamp: int):
        if self.voice_stream is None:
            if self.user_id is None or self.voice_stream_factory is None:
                self._buffered_data.append(opus_audio_data)
                return

            if len(opus_audio_data) >= 3 and opus_audio_data[-3:] == VoiceChannel.SILENCE_BYTES:
                return

            self._create_voice_stream()
            self.voice_stream.on_start()

        self._sliding_window.add_data(sequence, (timestamp, opus_audio_data))

        # Check for explicit silence frames
        if len(opus_audio_data) >= 3 and opus_audio_data[-3:] == VoiceChannel.SILENCE_BYTES:
            self._silence_counter += 1
            if self._silence_counter >= VoiceChannel.MIN_SILENT_FRAMES:
                self._sliding_window.flush()
                self._silence_counter = 0
                self.voice_stream.on_end()
                self.voice_stream = None
