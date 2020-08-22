import asyncio
import functools
import logging
import struct
from typing import Optional, Dict

from bidict import bidict

from .voice_channel import VoiceChannel
from .voice_stream import VoiceStreamFactory

try:
    import nacl.secret

    has_nacl = True
except ImportError:
    has_nacl = False

log = logging.getLogger(__name__)


class VoiceProcessor:
    def __init__(self):
        self.user_ssrc_map: bidict[int, int] = bidict()
        self.ssrc_channel_map: Dict[int, VoiceChannel] = {}
        self.voice_stream_factory: Optional[VoiceStreamFactory] = None

    def add_user_ssrc(self, user_id, ssrc):
        self.user_ssrc_map[ssrc] = user_id
        if ssrc in self.ssrc_channel_map:
            channel = self.ssrc_channel_map[ssrc]
            channel.set_user(user_id)
        else:
            channel = VoiceChannel(ssrc, self.voice_stream_factory)
            channel.set_user(user_id)
            self.ssrc_channel_map[ssrc] = channel

    def remove_user_ssrc(self, user_id=None, ssrc=None):
        if user_id in self.user_ssrc_map.inverse:
            ssrc = self.user_ssrc_map.inverse[user_id]
            del self.ssrc_channel_map[ssrc]
            del self.user_ssrc_map.inverse[user_id]
            return

        if ssrc in self.user_ssrc_map:
            del self.ssrc_channel_map[ssrc]
            del self.user_ssrc_map[ssrc]
            return

    async def start(self, socket, secret_key, mode, event_loop, voice_stream_factory):
        self.voice_stream_factory = voice_stream_factory
        for channel in self.ssrc_channel_map.values():
            channel.set_voice_stream_factory(voice_stream_factory)
        func = functools.partial(VoiceClientProtocol, secret_key, mode, self._handle_voice_packet)
        await event_loop.create_datagram_endpoint(func, sock=socket)

    def _handle_voice_packet(self,
                             version: int,
                             payload_type: int,
                             sequence: int,
                             timestamp: int,
                             ssrc: int,
                             header_extension: bytes,
                             data: bytes):

        # Check if we have a voice channel already
        if ssrc not in self.ssrc_channel_map:
            assert self.voice_stream_factory is not None
            channel = VoiceChannel(ssrc, self.voice_stream_factory)
            self.ssrc_channel_map[ssrc] = channel

        # On data
        channel = self.ssrc_channel_map[ssrc]
        channel.on_data(data=data,
                        sequence=sequence,
                        timestamp=timestamp)


class VoiceClientProtocol(asyncio.DatagramTransport):
    VOICE_PROTOCOL_VERSION = 0x90
    RTP_EXTENSION_HEADER_LENGTH = 8  # Two words

    def __init__(self, secret_key, mode: str, callback):
        super().__init__()
        self.box = nacl.secret.SecretBox(bytes(secret_key))
        self.mode = mode
        self.callback = callback

    def _unpack_header(self, data):
        version, payload_type, sequence, timestamp, ssrc = struct.unpack_from('>ccHII', data)
        return version, payload_type, sequence, timestamp, ssrc

    def _decrypt_xsalsa20_poly1305(self, data: bytes):
        nonce = bytearray(24)
        nonce[:12] = data[:12]
        header = self._unpack_header(data)
        text = self.box.decrypt(data[12:], nonce=bytes(nonce))
        return header, text

    def _decrypt_xsalsa20_poly1305_suffix(self, data: bytes):
        nonce = bytearray(24)
        nonce[:24] = data[-24:]
        header = self._unpack_header(data)
        text = self.box.decrypt(data[12:-24], nonce=bytes(nonce))
        return header, text

    def _decrypt_xsalsa20_poly1305_lite(self, data: bytes):
        nonce = bytearray(24)
        nonce[:4] = data[-4:]
        header = self._unpack_header(data)
        text = self.box.decrypt(data[12:-4], nonce=bytes(nonce))
        return header, text

    def datagram_received(self, encrypted_data: bytes, _addr):
        # Inspect the voice version first
        if encrypted_data[0] < VoiceClientProtocol.VOICE_PROTOCOL_VERSION:
            return

        decrypt_packet = getattr(self, '_decrypt_' + self.mode)
        header, decrypted_data = decrypt_packet(encrypted_data)
        version, payload_type, sequence, timestamp, ssrc = header

        header_extension = decrypted_data[:VoiceClientProtocol.RTP_EXTENSION_HEADER_LENGTH]
        opus_encoded_audio_data = decrypted_data[VoiceClientProtocol.RTP_EXTENSION_HEADER_LENGTH:]

        self.callback(version=version,
                      payload_type=payload_type,
                      sequence=sequence,
                      timestamp=timestamp,
                      ssrc=ssrc,
                      header_extension=header_extension,
                      data=opus_encoded_audio_data)

    def connection_made(self, _):
        pass

    def connection_lost(self, _):
        pass

    def error_received(self, err):
        log.error('Error in VoiceClientProtocol %s', err)
