import argparse
import asyncio

import cv2

from video_streaming_client import VideoStreamingClient


async def main():
    parser = argparse.ArgumentParser(description="WebRTC client example")
    parser.add_argument(
        "--ip", default="localhost", help="The IP address of the server"
    )
    args = parser.parse_args()

    # クライアントの作成
    client = VideoStreamingClient()

    # 受信したフレームを水平反転する処理を設定
    client.set_frame_processor(lambda frame: cv2.flip(frame, 1))

    print("Connecting to server...")
    print("Press 'q' to quit")

    try:
        # サーバーに接続（デフォルトでlocalhost:8080）
        await client.connect(f"http://{args.ip}:8080")

        # 接続が維持されている間待機
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("\nClosing connection...")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
