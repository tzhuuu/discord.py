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


class VoiceProcessorParams:
    def __init__(self,
                 *,
                 socket,
                 secret_key,
                 mode,
                 event_loop,
                 voice_stream_factory):
        self.socket = socket
        self.secret_key = secret_key
        self.mode = mode
        self.event_loop = event_loop
        self.voice_stream_factory = voice_stream_factory


class VoiceProcessor:
    def __init__(self):
        self.user_ssrc_map: bidict[int, int] = bidict()
        self.ssrc_channel_map: Dict[int, VoiceChannel] = {}
        self.params: Optional[VoiceProcessorParams] = VoiceProcessorParams(socket=None,
                                                                           secret_key=None,
                                                                           mode=None,
                                                                           event_loop=None,
                                                                           voice_stream_factory=None)
        self.datagram_transport = None
        self.should_reconnect = False
        self.socket = None
        self.event_loop = None

    def add_user_ssrc(self, user_id, ssrc):
        self.user_ssrc_map[ssrc] = user_id
        if ssrc in self.ssrc_channel_map:
            channel = self.ssrc_channel_map[ssrc]
            channel.set_user(user_id)
        else:
            channel = VoiceChannel(ssrc, self.params.voice_stream_factory)
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
        self.params = VoiceProcessorParams(socket=socket,
                                           secret_key=secret_key,
                                           mode=mode,
                                           event_loop=event_loop,
                                           voice_stream_factory=voice_stream_factory)
        self.socket = socket
        self.should_reconnect = True
        self.event_loop = event_loop
        for channel in self.ssrc_channel_map.values():
            channel.set_voice_stream_factory(self.params.voice_stream_factory)
        await self._create_datagram_endpoint()

    async def stop(self):
        # if self.datagram_transport is not None:
        #     self.datagram_transport.close()
        self.should_reconnect = False

    async def _create_datagram_endpoint(self):
        func = functools.partial(VoiceClientProtocol,
                                 self.params.secret_key,
                                 self.params.mode,
                                 self._handle_voice_packet,
                                 self._handle_connection_made,
                                 self._handle_connection_lost,
                                 self._handle_error_received)
        await self.event_loop.create_datagram_endpoint(func, sock=self.socket)

    async def _reconnect(self):
        if self.socket is None:
            log.info('Failed to reconnect because socket is None')
            return

        log.info('Reconnecting the voice udp socket')
        await self._create_datagram_endpoint()

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
            assert self.params.voice_stream_factory is not None
            channel = VoiceChannel(ssrc, self.params.voice_stream_factory)
            self.ssrc_channel_map[ssrc] = channel

        # On data
        channel = self.ssrc_channel_map[ssrc]
        channel.on_data(opus_audio_data=data,
                        sequence=sequence,
                        timestamp=timestamp)

    def _handle_connection_made(self, transport):
        log.info('Connection made %s', transport)
        self.datagram_transport = transport

    def _handle_connection_lost(self, err):
        log.info('Voice udp connection lost: %s', err)
        if self.should_reconnect:
            self._reconnect()

    def _handle_error_received(self, err):
        log.info('Voice udp connection error: %s', err)
        if self.should_reconnect:
            self._reconnect()


class VoiceClientProtocol(asyncio.DatagramTransport):
    VOICE_PROTOCOL_VERSION = 0x90
    RTP_EXTENSION_HEADER_LENGTH = 8  # Two words

    def __init__(self,
                 secret_key,
                 mode: str,
                 data_callback,
                 connection_made_cb,
                 connection_lost_cb,
                 error_received_cb):
        super().__init__()
        self.box = nacl.secret.SecretBox(bytes(secret_key))
        self.mode = mode
        self.callback = data_callback
        self.connection_made_cb = connection_made_cb
        self.connection_lost_cb = connection_lost_cb
        self.error_received_cb = error_received_cb

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

    def connection_made(self, transport):
        self.connection_made_cb(transport)

    def connection_lost(self, err):
        self.connection_lost_cb(err)

    def error_received(self, err):
        self.error_received_cb(err)
