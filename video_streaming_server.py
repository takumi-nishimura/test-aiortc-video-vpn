import asyncio
import json
from typing import Callable, Optional, Set

import cv2
import numpy as np
from aiohttp import web
from aiortc import (
    MediaStreamTrack,
    RTCConfiguration,
    RTCIceServer,
    RTCPeerConnection,
    RTCRtpSender,
    RTCSessionDescription,
)
from aiortc.contrib.media import MediaRelay
from av import VideoFrame


class VideoProcessor(MediaStreamTrack):
    """ビデオストリームを処理するベースクラス"""

    kind = "video"

    def __init__(self, track: MediaStreamTrack):
        super().__init__()
        self.track = track
        self._process_frame: Optional[Callable] = None

    def set_processor(self, processor: Callable):
        """ビデオフレーム処理関数を設定"""
        self._process_frame = processor

    async def recv(self):
        frame = await self.track.recv()

        if self._process_frame is None:
            return frame

        try:
            # フレームをnumpy配列に変換
            img = frame.to_ndarray(format="yuv420p")  # type: ignore
            bgr = cv2.cvtColor(img, cv2.COLOR_YUV2BGR_I420)

            # 処理関数を適用
            processed_bgr = self._process_frame(bgr)

            # YUV420pに戻す
            yuv = cv2.cvtColor(processed_bgr, cv2.COLOR_BGR2YUV_I420).astype(
                np.uint8
            )
            new_frame = VideoFrame.from_ndarray(yuv, format="yuv420p")
            new_frame.pts = frame.pts if frame.pts is not None else 0
            new_frame.time_base = frame.time_base

            return new_frame
        except Exception as e:
            print(f"Error processing video frame: {e}")
            return frame


class VideoStreamingServer:
    """WebRTCビデオストリーミングサーバー"""

    def __init__(self, host: str = "0.0.0.0", port: int = 8080):
        self.host = host
        self.port = port
        self.pcs: Set[RTCPeerConnection] = set()
        self.relay = MediaRelay()
        self.app = web.Application()
        self.processor_factory = lambda track: VideoProcessor(track)

    def set_video_processor(
        self, processor_factory: Callable[[MediaStreamTrack], VideoProcessor]
    ):
        """カスタムビデオプロセッサーを設定"""
        self.processor_factory = processor_factory

    async def _handle_offer(self, request: web.Request) -> web.Response:
        params = await request.json()
        offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])

        pc = RTCPeerConnection(
            RTCConfiguration(
                iceServers=[RTCIceServer(urls="stun:stun.l.google.com:19302")]
            )
        )
        self.pcs.add(pc)

        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            print(f"Connection state is: {pc.connectionState}")
            if pc.connectionState == "failed":
                await pc.close()
                self.pcs.discard(pc)

        # トランシーバーの設定
        transceiver = pc.addTransceiver("video", direction="sendrecv")
        transceiver.setCodecPreferences(
            [
                codec
                for codec in RTCRtpSender.getCapabilities("video").codecs
                if codec.mimeType.lower() in ["video/h264", "video/vp8"]
            ]
        )

        @pc.on("track")
        def on_track(track):
            if track.kind == "video":
                processor = self.processor_factory(self.relay.subscribe(track))
                pc.addTrack(processor)

        await pc.setRemoteDescription(offer)
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        return web.Response(
            content_type="application/json",
            text=json.dumps(
                {
                    "sdp": pc.localDescription.sdp,
                    "type": pc.localDescription.type,
                }
            ),
        )

    async def _on_shutdown(self, app):
        coros = [pc.close() for pc in self.pcs]
        await asyncio.gather(*coros)
        self.pcs.clear()

    def run(self):
        """サーバーを起動"""
        self.app.on_shutdown.append(self._on_shutdown)
        self.app.router.add_post("/offer", self._handle_offer)
        web.run_app(self.app, host=self.host, port=self.port)


# 使用例
if __name__ == "__main__":
    # エッジ検出を行うプロセッサーの例
    class EdgeDetectionProcessor(VideoProcessor):
        def __init__(self, track):
            super().__init__(track)
            self.set_processor(lambda frame: cv2.Canny(frame, 100, 200))

    server = VideoStreamingServer()
    server.set_video_processor(EdgeDetectionProcessor)
    server.run()
