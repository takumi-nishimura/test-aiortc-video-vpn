import cv2

from video_streaming_server import VideoProcessor, VideoStreamingServer


class GrayscaleProcessor(VideoProcessor):
    """グレースケール変換を行うプロセッサー"""

    def __init__(self, track):
        super().__init__(track)
        self.set_processor(self._process_to_grayscale)

    def _process_to_grayscale(self, frame):
        """フレームをグレースケールに変換"""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def main():
    # サーバーの作成
    server = VideoStreamingServer(host="0.0.0.0", port=8080)

    # グレースケールプロセッサーを設定
    server.set_video_processor(GrayscaleProcessor)

    print("Starting server on http://localhost:8080")
    print("Press Ctrl+C to stop the server")

    # サーバーの起動
    server.run()


if __name__ == "__main__":
    main()
