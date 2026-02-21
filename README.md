# NEV GCS

Hunter 2.0 UGV 원격 제어 서버.
차량의 ROS2 노드(`nev_remote`, `hunter_teleop_mux`)와 UDP로 통신하며,
웹 UI를 통해 차량 상태 모니터링 및 원격 제어 명령을 송수신한다.

> **ROS2 불필요** — 순수 Python 애플리케이션이며 차량과 UDP로만 통신한다.

---

## 목차

1. [시스템 구성](#1-시스템-구성)
2. [파일 구조](#2-파일-구조)
3. [의존성 설치](#3-의존성-설치)
4. [설정 (config.yaml)](#4-설정-configyaml)
5. [실행](#5-실행)
6. [웹 UI](#6-웹-ui)
7. [UDP 패킷 프로토콜](#7-udp-패킷-프로토콜)
8. [상태 검증 로직](#8-상태-검증-로직)
9. [조이스틱 입력](#9-조이스틱-입력)
10. [REST API](#10-rest-api)
11. [WebSocket](#11-websocket)
12. [로컬 테스트 절차](#12-로컬-테스트-절차)
13. [관련 차량 패키지](#13-관련-차량-패키지)

---

## 1. 시스템 구성

```
┌─────────────────────────────────────┐     ┌────────────────────────────────────────────┐
│            서버 (이 패키지)           │     │                    차량                     │
│                                     │     │                                            │
│  [브라우저]                          │     │  [hunter_base]                             │
│      │ WebSocket / REST             │     │       │ /cmd_vel  ◄──────────────┐         │
│      ▼                              │     │       │                          │ remap    │
│  [nev_gcs]                   │     │  [mux_node]  ── /final_cmd ─────┘         │
│   - UDP 송수신                       │     │       │                                    │
│   - 조이스틱 읽기                    │◄───►│       │ /mux_status, /estop_status         │
│   - 상태 검증                        │ UDP │       ▲                                    │
│   - 웹 서버                         │     │  [net_bridge]                              │
└─────────────────────────────────────┘     │       │ /teleop_cmd, /emergency_stop       │
                                            │       │ /cmd_mode_request                  │
                                            │       ▲                                    │
                                            │  [system_monitor]                          │
                                            │       │ /system_monitor/{cpu,mem,disk,...} │
                                            └────────────────────────────────────────────┘
```

### 포트

| 방향 | 서버 포트 | 차량 포트 |
|------|-----------|-----------|
| 서버 수신 (차량 → 서버) | **5000** (`rx_port`) | — |
| 차량 수신 (서버 → 차량) | — | **5001** (`vehicle_port`) |
| 웹 UI | **8080** | — |

---

## 2. 파일 구조

```
nev_gcs/
├── main.py              진입점. asyncio로 모든 서브시스템 조율
├── config.yaml          설정 파일 (IP, 포트, 조이스틱 등)
│
├── state.py             SharedState — 모든 차량·서버 상태 컨테이너
│                        상태 검증(validation)과 WebSocket 브로드캐스트 담당
│
├── vehicle_bridge.py    asyncio UDP 프로토콜
│                        패킷 파싱(수신) / HB·TC·ES·CM 송신 / 주기적 송신 루프
│
├── joystick.py          pygame 백그라운드 스레드
│                        조이스틱 축값 → state.control 업데이트
│
├── tools/
│   └── joystick_test.py 조이스틱 축 인덱스 확인용 독립 스크립트
│
└── web/
    ├── server.py        FastAPI 앱 팩토리
    │                    REST 엔드포인트 + WebSocket 엔드포인트
    └── static/
        ├── index.html   단일 페이지 대시보드 (영상 + 우측 상태 패널)
        ├── app.js       WebSocket 클라이언트 + UI 렌더링
        └── style.css    다크 테마 스타일
```

---

## 3. 의존성 설치

```bash
pip3 install fastapi "uvicorn[standard]" pyyaml pygame
```

### 선택 의존성

| 패키지 | 용도 | 없으면 |
|--------|------|--------|
| `pygame` | 조이스틱 입력 | 조이스틱 비활성화, 나머지 정상 동작 |

---

## 4. 설정 (config.yaml)

```yaml
# 차량 UDP
vehicle_ip:   "127.0.0.1"   # 차량 IP (로컬 테스트: 127.0.0.1)
vehicle_port: 5001           # 차량 수신 포트 (net_bridge local_port)
rx_port:      5000           # 서버 수신 포트 (net_bridge server_port)

# 웹 서버
web_port: 8080

# 송신 주기
heartbeat_rate:       5.0    # Hz — HB 패킷 송신
teleop_rate:         20.0    # Hz — TC 패킷 송신 (mode=2 일 때만)
state_push_interval:  0.5    # sec — 브라우저 UI 갱신 주기

# 조이스틱
joystick:
  axis_speed:     1      # 왼쪽 스틱 Y  → linear_x
  axis_steer:     3      # 오른쪽 스틱 X → angular_z (조향각 rad)
  axis_raw_speed: 1      # raw_speed 표시용 축
  axis_raw_steer: 3      # raw_steer 표시용 축
  btn_estop:      4      # E-stop 토글 버튼 (LB/RB)
  max_speed:      1.0    # 최대 속도 (m/s)
  max_steer_deg:  27.0   # 최대 조향각 (도) — Hunter 2.0 물리적 한계
  deadzone:       0.05   # 축 데드존
  invert_speed:   true   # 스틱 앞으로 = 양수 linear_x
```

---

## 5. 실행

### 기본 실행

```bash
cd /home/nev/dev/nev_gcs
python3 main.py
```

### 옵션 오버라이드

```bash
# 실제 차량 IP 지정
python3 main.py --vehicle-ip 192.168.1.100

# 포트 변경
python3 main.py --rx-port 5000 --vehicle-port 5001 --web-port 8080

# 다른 config 파일
python3 main.py --config /path/to/my_config.yaml
```

### 실행 시 출력 예시

```
12:34:56  INFO     main: UDP  listen=5000  vehicle=127.0.0.1:5001
12:34:56  INFO     main: Web  http://0.0.0.0:8080
12:34:56  INFO     joystick: Joystick connected: Xbox 360 Controller
```

---

## 6. 웹 UI

브라우저에서 `http://localhost:8080` 접속.

### 레이아웃

```
┌─────────────────────────────────────────────────────────────────┐
│  NEV GCS  [WS] [VEH] [REM]  RTT: 3.2ms  12:34:56    │  ← topbar
├─────────────────────────────────────────────────────────────────┤
│  MODE: [IDLE] [CTRL] [NAV] [REMOTE]                [■ E-STOP]  │  ← cmdbar
├────────────────────────────────────┬────────────────────────────┤
│                                    │ HUNTER                     │
│                                    │ MUX                        │
│            VIDEO FEED              │ NETWORK                    │
│          (NO SIGNAL)               │ TWIST                      │
│                                    │ E-STOP                     │
│                                    │ JOYSTICK                   │
│                                    │ RESOURCES (CPU/RAM/GPU)    │
│                                    │ DISK                       │
│                                    │ NET INTERFACES             │
│                                    │ ALERTS                     │
└────────────────────────────────────┴────────────────────────────┘
```

### 헤더 배지

| 배지 | 초록 | 빨강/회색 |
|------|------|-----------|
| `WS`  | WebSocket 연결됨 | 끊김 |
| `VEH` | 차량 데이터 수신 중 | `NO DATA` 또는 `Ns` |
| `REM` | `remote_enabled=true` | 회색 |

### 모드 버튼

| 버튼 | mode 값 | 동작 |
|------|---------|------|
| IDLE   | `-1` | 차량 정지 (idle) |
| CTRL   | `0`  | 컨트롤러 켜짐, 제어 없음 |
| NAV    | `1`  | `/cmd_vel` 자율주행 |
| REMOTE | `2`  | 원격 조종 활성화 |

### E-STOP 버튼

- 누르면 `ES` 패킷 전송 → 차량 즉시 정지
- 버튼 및 E-STOP 카드 전체가 빨간 pulse 애니메이션으로 전환
- 다시 누르면 E-stop 해제

---

## 7. UDP 패킷 프로토콜

모든 패킷은 **2바이트 ASCII 헤더 + 리틀 엔디언 바이너리 구조체**로 구성된다.

### 서버 → 차량 (송신)

| 헤더 | 포맷 | 크기 | 내용 | 송신 주기 |
|------|------|------|------|-----------|
| `HB` | `<2sdH`  | 12B | heartbeat (timestamp, seq) | 5 Hz |
| `TC` | `<2sffH` | 12B | 조종 명령 (linear_x, angular_z, seq) | 20 Hz (mode=2) |
| `ES` | `<2sBH`  | 5B  | E-stop (0=해제, 1=발동, seq) | 이벤트 |
| `CM` | `<2sbH`  | 5B  | 모드 변경 (mode, seq) | 이벤트 |

### 차량 → 서버 (수신)

**차량 상태**

| 헤더 | 포맷 | 내용 | 대응 state 키 |
|------|------|------|---------------|
| `MS` | `<2sbbbbbbBH` | mux 상태 | `state.mux` |
| `TV` | `<2sffffffH`  | nav/teleop/final twist | `state.twist` |
| `NS` | `<2sBbffH`   | 네트워크 상태 | `state.network` |
| `HS` | `<2sddBBHdH` | Hunter 차량 상태 | `state.hunter` |
| `EP` | `<2sBbbH`   | E-stop 상태 | `state.estop` |
| `RE` | `<2sBH`     | remote_enabled 파라미터 | `state.remote_enabled` |

**시스템 리소스** (1 Hz, `system_monitor` 노드 경유)

| 헤더 | 포맷 | 내용 | 대응 state 키 |
|------|------|------|---------------|
| `CR` | `<2sffffffqH` | CPU 사용률·주파수·온도·로드·컨텍스트 스위치 | `state.resources` |
| `MR` | `<2sqqqqfH`   | 메모리 total/avail/used/free | `state.resources` |
| `GR` | `<2sifffffH`  | GPU별 사용률·메모리·온도·전력 (gpu_idx 기준) | `state.gpu_list[idx]` |
| `DI` | `<2sqqqqqqqH` | 디스크 I/O 총계 | (last_vehicle_recv 갱신) |
| `DP` | `<2sB32sqqqfBH` | 파티션별 마운트포인트·용량·사용률 | `state.disk_partitions[idx]` |
| `NM` | `<2siiiH`     | 네트워크 인터페이스 요약 (total/active/down) | `state.resources` |
| `NF` | `<2sB16sBiiddqqqqqqqqH` | 인터페이스별 이름·상태·속도·트래픽 | `state.net_interfaces[idx]` |

### E-stop `bridge_flag` 값

| 값 | 의미 |
|----|------|
| `0` | 정상 |
| `1` | 서버가 명시적으로 E-stop 명령 |
| `2` | 소켓 오류 |
| `3` | heartbeat 타임아웃 |
| `4` | 원격 모드 중 조종 명령 타임아웃 |

### E-stop `mux_flag` 값

| 값 | 의미 |
|----|------|
| `0` | 정상 |
| `1` | remote 모드 + nav 활성 + teleop 없음 |

---

## 8. 상태 검증 로직

`state.py`의 `_validate()` 메서드가 매 패킷 수신 시 + 0.5초 주기로 실행된다.
검증 결과는 UI의 **ALERTS** 카드에 실시간으로 표시된다.

| 조건 | 레벨 | 메시지 |
|------|------|--------|
| E-stop 중인데 `final_cmd` 이동값 감지 | `error` | `E-STOP active but vehicle is moving!` |
| 서버가 E-stop 송신했는데 차량 미확인 | `warn` | `E-stop sent — waiting for vehicle confirmation` |
| remote 모드인데 teleop 미수신 | `warn` | `Remote mode active but no teleop commands received` |
| 차량 데이터 3초 이상 미수신 | `error` | `No vehicle data for Xs` |

---

## 9. 조이스틱 입력

`joystick.py`는 pygame을 통해 조이스틱 축값을 읽어 직접 제어값으로 변환한다.

```
linear_x  = -axis_speed_raw × max_speed   (invert_speed=true 기준)
angular_z =  axis_steer_raw × max_steer_rad
```

- **데드존 처리**: `|axis| < deadzone` 이면 0, 나머지 구간은 선형 정규화
- **angular_z**: TC 패킷의 angular_z 필드로 전송되며, 차량(net_bridge)이 `/remote/teleop_cmd`로 발행
- **표시용 raw 축**: `axis_raw_speed`, `axis_raw_steer`는 UI 표시 전용이며 실제 제어에 미사용
- **자동 재연결**: 조이스틱 연결 해제 시 1초 주기로 재연결 시도
- **E-stop 버튼**: `btn_estop` 버튼 상승 엣지(rising edge)에서 E-stop 토글

---

## 10. REST API

서버 구동 후 `http://localhost:8080` 기준.

### `GET /api/state`

현재 전체 상태를 JSON으로 반환. WebSocket 연결 전 초기 로드에 사용.

```json
{
  "mux":             { "requested_mode": 2, "active_source": 1, ... },
  "twist":           { "nav_lx": 0.0, "teleop_lx": 0.5, "final_lx": 0.5, ... },
  "network":         { "connected": true, "rtt_ms": 3.2, ... },
  "hunter":          { "linear_vel": 0.5, "battery_voltage": 24.1, ... },
  "estop":           { "is_estop": false, "bridge_flag": 0, "mux_flag": 0 },
  "resources":       { "cpu_usage": 32.1, "ram_used": 4096, ... },
  "gpu_list":        [ { "gpu_usage": 12.0, "gpu_temp": 65.0, ... } ],
  "disk_partitions": [ { "mountpoint": "/", "percent": 50.0, ... } ],
  "net_interfaces":  [ { "name": "eth0", "is_up": true, ... } ],
  "control":         { "mode": 2, "estop": false, "linear_x": 0.5, "angular_z": 0.3 },
  "alerts":          [],
  "server_time":     1700000000.0,
  "vehicle_age":     0.12
}
```

### `POST /api/cmd_mode`

```json
{ "mode": 2 }
```

`mode`: `-1`(idle) / `0`(ctrl_on) / `1`(nav) / `2`(remote)
→ 차량으로 `CM` 패킷 즉시 송신.

```json
{ "ok": true, "mode": 2 }
```

### `POST /api/estop`

```json
{ "active": true }
```

→ 차량으로 `ES` 패킷 즉시 송신. `active: false`로 해제.

```json
{ "ok": true, "active": true }
```

---

## 11. WebSocket

`ws://localhost:8080/ws`

연결 즉시 현재 상태 전송 → 이후 상태 변경 시마다 자동 push.
최대 5초 무변화 시 keepalive로 현재 상태 재전송.

---

## 12. 로컬 테스트 절차

모든 ROS2 터미널에 공통으로 적용:

```bash
source /opt/ros/humble/setup.bash
source /home/nev/dev/ros2_ws/install/setup.bash
```

### 터미널 1 — mux_node

```bash
ros2 run hunter_teleop_mux mux_node.py \
  --ros-args -p remote_enabled:=true
```

> 기본값 `remote_enabled=false` → 테스트 시 반드시 `true`로 지정

### 터미널 2 — net_bridge

launch 파일 사용:

```bash
ros2 launch nev_remote net_bridge.launch.py
```

또는 파라미터 직접 지정:

```bash
ros2 run nev_remote net_bridge.py \
  --ros-args \
    -p server_ip:=127.0.0.1 \
    -p server_port:=5000 \
    -p local_port:=5001
```

### 터미널 3 — system_monitor (리소스 모니터링)

```bash
ros2 launch system_monitor system_monitor.launch.py
```

### 터미널 4 — mock_hunter_base (하드웨어 없을 때)

```bash
ros2 run hunter_teleop mock_hunter_base.py \
  --ros-args -r cmd_vel:=/final_cmd
```

### 터미널 5 — 서버

```bash
cd /home/nev/dev/nev_gcs
python3 main.py
```

브라우저 접속: **http://localhost:8080**

---

### 단계별 확인

**1. 연결 확인**

```bash
ros2 topic echo /vehicle/mux_status
ros2 topic hz  /final_cmd        # 20Hz 발행 여부
```

UI에서 헤더 배지 `VEH` 초록색, RTT 값 표시 확인

**2. 모드 전환**

```bash
ros2 topic echo /remote/cmd_mode
```

브라우저에서 `NAV` → `REMOTE` 클릭 시마다 토픽 메시지 수신 확인

**3. 원격 제어 흐름**

브라우저에서 `REMOTE` 선택 → mode=2 전송 → mux가 teleop 소스 선택
조이스틱 연결 시 TWIST 카드의 `teleop` / `final` 값이 변화하는지 확인

```bash
ros2 topic echo /remote/teleop_cmd
ros2 topic echo /final_cmd
```

**4. E-stop**

```bash
ros2 topic echo /vehicle/estop_status
ros2 topic echo /remote/estop_status
```

| 동작 | 기대 결과 |
|------|-----------|
| E-STOP 버튼 누름 | `bridge_flag=1`, `is_estop=true`, `final_cmd=0/0` |
| RELEASE 버튼 누름 | `bridge_flag=0`, `is_estop=false` |
| net_bridge 종료 | `bridge_flag=3` (HB 타임아웃) |

---

## 13. 관련 차량 패키지

| 패키지 | 위치 | 역할 |
|--------|------|------|
| `nev_remote` | `ros2_ws/src/nev_remote/nev_remote` | 차량-서버 UDP 브리지 (`net_bridge` 노드) |
| `nev_remote_msgs` | `ros2_ws/src/nev_remote/nev_remote_msgs` | 공용 ROS2 메시지 정의 |
| `hunter_teleop_mux` | `ros2_ws/src/hunter_teleop_mux` | 명령 우선순위 중재 (`mux_node`) |
| `system_monitor` | `ros2_ws/src/system_monitor` | CPU/메모리/디스크/네트워크/GPU 모니터링 |
| `system_monitor_msgs` | `ros2_ws/src/system_monitor_msgs` | system_monitor 메시지 정의 |
| `hunter_msgs` | `ros2_ws/src/hunter_ros2/hunter_msgs` | Hunter 차량 상태 메시지 |
| `hunter_base` | `ros2_ws/src/hunter_ros2/hunter_base` | 실제 하드웨어 드라이버 |

### `/final_cmd` → `/cmd_vel` 리맵

`mux_node`는 `/final_cmd`로 발행하지만 `hunter_base`는 `/cmd_vel`을 구독한다.
실제 하드웨어 구동 시 `hunter_base` 실행 때 리맵 필요:

```bash
ros2 run hunter_base hunter_base_node \
  --ros-args -r /cmd_vel:=/final_cmd
```
