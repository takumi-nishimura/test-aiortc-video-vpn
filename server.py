import asyncio
import json

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
from aiortc.contrib.media import MediaBlackhole, MediaRelay
from av import VideoFrame


class VideoTransformTrack(MediaStreamTrack):
    kind = "video"

    def __init__(self, track):
        super().__init__()
        self.track = track

    async def recv(self):
        frame = await self.track.recv()

        try:
            # YUV420pフォーマットで画像を取得
            img = frame.to_ndarray(format="yuv420p")

            # BGRに変換
            bgr = cv2.cvtColor(img, cv2.COLOR_YUV2BGR_I420)

            # エッジ検出
            edges = cv2.Canny(bgr, 100, 200)
            edges_bgr = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)

            # YUV420pに戻す
            yuv = cv2.cvtColor(edges_bgr, cv2.COLOR_BGR2YUV_I420).astype(
                np.uint8
            )
            new_frame = VideoFrame.from_ndarray(yuv, format="yuv420p")
            new_frame.pts = frame.pts
            new_frame.time_base = frame.time_base

            return new_frame
        except Exception as e:
            print(f"Error processing video frame: {e}")
            return frame  # エラーが発生した場合は元のフレームを返す


pcs = set()
relay = MediaRelay()


async def offer(request):
    params = await request.json()
    offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])

    config = RTCConfiguration(
        iceServers=[RTCIceServer(urls="stun:stun.l.google.com:19302")]
    )
    pc = RTCPeerConnection(config)
    pcs.add(pc)
    print("New peer connection created")

    @pc.on("iceconnectionstatechange")
    async def on_iceconnectionstatechange():
        print("ICE Connection state is:", pc.iceConnectionState)

    @pc.on("icegatheringstatechange")
    async def on_icegatheringstatechange():
        print("ICE Gathering state is:", pc.iceGatheringState)

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        print("Connection state is:", pc.connectionState)
        if pc.connectionState == "failed":
            await pc.close()
            pcs.discard(pc)

    # トランシーバーを先に設定
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
        print(f"Track received: {track.kind}")
        if track.kind == "video":
            transformed_track = VideoTransformTrack(relay.subscribe(track))
            pc.addTrack(transformed_track)
            print("Video track added to peer connection")

        @track.on("ended")
        async def on_ended():
            print(f"Track ended: {track.kind}")

    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return web.Response(
        content_type="application/json",
        text=json.dumps(
            {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}
        ),
    )


async def on_shutdown(app):
    coros = [pc.close() for pc in pcs]
    await asyncio.gather(*coros)
    pcs.clear()


if __name__ == "__main__":
    app = web.Application()
    app.on_shutdown.append(on_shutdown)
    app.router.add_post("/offer", offer)
    web.run_app(app, host="0.0.0.0", port=8080)
