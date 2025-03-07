import argparse
import asyncio
import json

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
from aiortc.contrib.media import MediaPlayer, MediaRecorder
from av import VideoFrame


class CameraStreamTrack(VideoStreamTrack):
    def __init__(self):
        super().__init__()
        self.cap = cv2.VideoCapture(0)
        if not self.cap.isOpened():
            raise RuntimeError("カメラを開けませんでした")

    async def recv(self):
        pts, time_base = await self.next_timestamp()

        ret, frame = self.cap.read()
        if not ret:
            raise RuntimeError("カメラからフレームを取得できませんでした")

        try:
            # フレームをYUV420pに変換し、uint8型に明示的に変換
            frame_yuv = cv2.cvtColor(frame, cv2.COLOR_BGR2YUV_I420).astype(
                np.uint8
            )

            # VideoFrameの作成
            video_frame = VideoFrame.from_ndarray(frame_yuv, format="yuv420p")
            video_frame.pts = pts
            video_frame.time_base = time_base
            return video_frame
        except Exception as e:
            print(f"Error converting camera frame: {e}")
            # エラーの場合は元のフレームをそのまま返す
            frame_yuv = cv2.cvtColor(frame, cv2.COLOR_BGR2YUV_I420).astype(
                np.uint8
            )
            fallback_frame = VideoFrame.from_ndarray(
                frame_yuv, format="yuv420p"
            )
            fallback_frame.pts = pts
            fallback_frame.time_base = time_base
            return fallback_frame


async def run(args):
    # WebRTCの設定（STUNサーバーを追加）とコーデック設定
    config = RTCConfiguration(
        iceServers=[RTCIceServer(urls="stun:stun.l.google.com:19302")]
    )
    pc = RTCPeerConnection(config)

    # トランシーバーの設定
    transceiver = pc.addTransceiver("video", direction="sendrecv")
    transceiver.setCodecPreferences(
        [
            codec
            for codec in RTCRtpSender.getCapabilities("video").codecs
            if codec.mimeType.lower() in ["video/h264", "video/vp8"]
        ]
    )

    # ICE接続状態の監視
    @pc.on("iceconnectionstatechange")
    async def on_iceconnectionstatechange():
        print("ICE Connection state is:", pc.iceConnectionState)

    # ICE候補の生成状態の監視
    @pc.on("icegatheringstatechange")
    async def on_icegatheringstatechange():
        print("ICE Gathering state is:", pc.iceGatheringState)

    # 処理済み映像の受信と表示の設定
    @pc.on("track")
    def on_track(track):
        print(f"Receiving track of kind: {track.kind}")

        if track.kind != "video":
            return

        async def show_processed_video():
            print("Starting video display loop")
            while pc.connectionState != "closed":
                try:
                    frame = await track.recv()
                    img = frame.to_ndarray(format="yuv420p")
                    img = cv2.cvtColor(img, cv2.COLOR_YUV2BGR_I420)

                    cv2.imshow("Processed Video", img)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
                except Exception as e:
                    print(f"Error receiving video: {e}")
                    if pc.connectionState == "failed":
                        break
                    await asyncio.sleep(0.1)
                    continue

        asyncio.ensure_future(show_processed_video())

    # カメラストリームの追加
    camera_track = CameraStreamTrack()
    pc.addTrack(camera_track)
    print("Camera track added to peer connection")

    # オファーの作成
    offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    print("Local description set")

    # ICE候補の収集完了を待機
    while pc.iceGatheringState != "complete":
        await asyncio.sleep(0.1)

    # サーバーへのオファー送信
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"http://{args.ip}:8080/offer",
            json={
                "sdp": pc.localDescription.sdp,
                "type": pc.localDescription.type,
            },
        ) as resp:
            if resp.status == 500:
                error_text = await resp.text()
                print(f"Server error: {error_text}")
                return

            content_type = resp.headers.get("Content-Type", "")
            if not content_type.startswith("application/json"):
                error_text = await resp.text()
                print(f"Unexpected content type: {content_type}")
                print(f"Response text: {error_text}")
                return

            try:
                answer = await resp.json()
                await pc.setRemoteDescription(
                    RTCSessionDescription(
                        sdp=answer["sdp"], type=answer["type"]
                    )
                )
            except (json.JSONDecodeError, KeyError) as e:
                print(f"Error processing server response: {e}")
                return

    # 接続状態の監視
    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        print("Connection state is:", pc.connectionState)
        if pc.connectionState == "failed":
            await pc.close()

    try:
        # 接続が維持されている間待機
        while pc.connectionState != "closed":
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        # クリーンアップ
        await pc.close()
        cv2.destroyAllWindows()
        camera_track.cap.release()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WebRTC client example")
    parser.add_argument(
        "--ip", default="localhost", help="The IP address of the server"
    )
    args = parser.parse_args()

    asyncio.run(run(args))
