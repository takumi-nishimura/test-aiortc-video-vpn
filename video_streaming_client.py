import asyncio
import json
from typing import Callable, Optional

import aiohttp
import cv2
import numpy as np
from aiortc import (
    RTCConfiguration,
    RTCIceServer,
    RTCPeerConnection,
    RTCRtpSender,
    RTCSessionDescription,
    VideoStreamTrack,
)
from av import VideoFrame


class CameraStreamTrack(VideoStreamTrack):
    """カメラからビデオストリームを取得するクラス"""

    def __init__(self, capture_device: int = 0):
        super().__init__()
        self.cap = cv2.VideoCapture(capture_device)
        if not self.cap.isOpened():
            raise RuntimeError("カメラを開けませんでした")

    async def recv(self):
        pts, time_base = await self.next_timestamp()

        ret, frame = self.cap.read()
        if not ret:
            raise RuntimeError("カメラからフレームを取得できませんでした")

        try:
            # フレームをYUV420pに変換
            frame_yuv = cv2.cvtColor(frame, cv2.COLOR_BGR2YUV_I420).astype(
                np.uint8
            )
            video_frame = VideoFrame.from_ndarray(frame_yuv, format="yuv420p")
            video_frame.pts = pts
            video_frame.time_base = time_base
            return video_frame
        except Exception as e:
            print(f"Error converting camera frame: {e}")
            return None

    def stop(self):
        """カメラリソースの解放"""
        if self.cap is not None:
            self.cap.release()


class VideoStreamingClient:
    """WebRTCビデオストリーミングクライアント"""

    def __init__(self):
        self.pc = None
        self.camera_track = None
        self._display_frame_processor: Optional[Callable] = None

    def set_frame_processor(self, processor: Callable):
        """表示フレームの処理関数を設定"""
        self._display_frame_processor = processor

    async def connect(self, server_url: str):
        """サーバーに接続"""
        config = RTCConfiguration(
            iceServers=[RTCIceServer(urls="stun:stun.l.google.com:19302")]
        )
        self.pc = RTCPeerConnection(config)

        # カメラトラックの追加
        self.camera_track = CameraStreamTrack()
        transceiver = self.pc.addTransceiver("video", direction="sendrecv")
        transceiver.setCodecPreferences(
            [
                codec
                for codec in RTCRtpSender.getCapabilities("video").codecs
                if codec.mimeType.lower() in ["video/h264", "video/vp8"]
            ]
        )
        self.pc.addTrack(self.camera_track)

        # 処理済みビデオの受信と表示の設定
        @self.pc.on("track")
        def on_track(track):
            if track.kind == "video":
                asyncio.create_task(self._show_video(track))

        # オファーの作成と送信
        offer = await self.pc.createOffer()
        await self.pc.setLocalDescription(offer)

        # ICE候補の収集完了を待機
        await self._wait_for_ice_complete()

        # サーバーにオファーを送信
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{server_url}/offer",
                json={
                    "sdp": self.pc.localDescription.sdp,
                    "type": self.pc.localDescription.type,
                },
            ) as resp:
                answer = await resp.json()
                await self.pc.setRemoteDescription(
                    RTCSessionDescription(
                        sdp=answer["sdp"], type=answer["type"]
                    )
                )

    async def _wait_for_ice_complete(self):
        """ICE候補の収集完了を待機"""
        while self.pc and self.pc.iceGatheringState != "complete":
            await asyncio.sleep(0.1)

    async def _show_video(self, track):
        """ビデオを表示"""
        while True:
            try:
                frame = await track.recv()
                if frame is None:
                    continue

                img = frame.to_ndarray(format="yuv420p")  # type: ignore
                bgr = cv2.cvtColor(img, cv2.COLOR_YUV2BGR_I420)

                if self._display_frame_processor:
                    bgr = self._display_frame_processor(bgr)

                cv2.imshow("Received Video", bgr)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
            except Exception as e:
                print(f"Error displaying video: {e}")
                if self.pc and self.pc.connectionState == "failed":
                    break
                await asyncio.sleep(0.1)

    async def disconnect(self):
        """接続を終了"""
        if self.pc:
            await self.pc.close()
        if self.camera_track:
            self.camera_track.stop()
        cv2.destroyAllWindows()


# 使用例
async def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="WebRTC video streaming client"
    )
    parser.add_argument(
        "--server",
        default="http://localhost:8080",
        help="Video streaming server URL",
    )
    args = parser.parse_args()

    client = VideoStreamingClient()

    # オプション：表示フレームの処理関数を設定
    # client.set_frame_processor(lambda frame: cv2.flip(frame, 1))  # 水平反転の例

    try:
        await client.connect(args.server)
        # 接続が維持されている間待機
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("Closing connection...")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
