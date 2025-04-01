class VideoStreamingClient {
    constructor() {
        this.pc = null;
        this.localStream = null;
        this.startButton = document.getElementById('startButton');
        this.stopButton = document.getElementById('stopButton');
        this.statusElement = document.getElementById('status');
        this.localVideo = document.getElementById('localVideo');
        this.remoteVideo = document.getElementById('remoteVideo');

        this.setupEventListeners();
    }

    setupEventListeners() {
        this.startButton.addEventListener('click', () => this.start());
        this.stopButton.addEventListener('click', () => this.stop());
    }

    async start() {
        try {
            // カメラストリームの取得
            this.localStream = await navigator.mediaDevices.getUserMedia({ video: true });
            this.localVideo.srcObject = this.localStream;

            // WebRTC接続の設定
            const config = {
                iceServers: [{ urls: 'stun:stun.l.google.com:19302' }]
            };
            this.pc = new RTCPeerConnection(config);

            // ローカルストリームの追加
            this.localStream.getTracks().forEach(track => {
                this.pc.addTrack(track, this.localStream);
            });

            // リモートストリームの処理
            this.pc.ontrack = (event) => {
                if (event.streams && event.streams[0]) {
                    this.remoteVideo.srcObject = event.streams[0];
                }
            };

            // 接続状態の監視
            this.pc.onconnectionstatechange = () => {
                this.updateStatus(this.pc.connectionState);
            };

            // ICE接続状態の監視
            this.pc.oniceconnectionstatechange = () => {
                console.log('ICE Connection State:', this.pc.iceConnectionState);
            };

            // オファーの作成と送信
            const offer = await this.pc.createOffer();
            await this.pc.setLocalDescription(offer);

            // ICE候補の収集完了を待機
            await this.waitForICEComplete();

            // サーバーにオファーを送信
            const response = await fetch('http://localhost:8080/offer', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    sdp: this.pc.localDescription.sdp,
                    type: this.pc.localDescription.type,
                }),
            });

            if (!response.ok) {
                throw new Error('サーバーとの通信に失敗しました');
            }

            const answer = await response.json();
            await this.pc.setRemoteDescription(new RTCSessionDescription(answer));

            // UIの更新
            this.startButton.disabled = true;
            this.stopButton.disabled = false;
            this.updateStatus('接続中');

        } catch (error) {
            console.error('Error:', error);
            this.updateStatus('エラー');
        }
    }

    async stop() {
        try {
            if (this.pc) {
                await this.pc.close();
                this.pc = null;
            }
            if (this.localStream) {
                this.localStream.getTracks().forEach(track => track.stop());
                this.localStream = null;
            }

            this.localVideo.srcObject = null;
            this.remoteVideo.srcObject = null;

            this.startButton.disabled = false;
            this.stopButton.disabled = true;
            this.updateStatus('未接続');
        } catch (error) {
            console.error('Error during cleanup:', error);
        }
    }

    updateStatus(status) {
        this.statusElement.textContent = status;
        this.statusElement.className = status === '接続中' ? 'connected' : '';
    }

    async waitForICEComplete() {
        return new Promise((resolve) => {
            if (this.pc.iceGatheringState === 'complete') {
                resolve();
            } else {
                this.pc.onicegatheringstatechange = () => {
                    if (this.pc.iceGatheringState === 'complete') {
                        resolve();
                    }
                };
            }
        });
    }
}

// クライアントのインスタンス化
const client = new VideoStreamingClient();
