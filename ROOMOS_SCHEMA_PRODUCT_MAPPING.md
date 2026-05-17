# RoomOS 26.5.1 Schema and Product Mapping

분석 대상:

```text
https://raw.githubusercontent.com/cisco-ce/roomos.cisco.com/master/schemas/26.5.1%20April%202026.json
```

참고 화면:

- `roomos.cisco.com` DevTools Sources의 `productHelper.js`
- schema product key를 사람이 읽는 공식 제품명으로 변환하는 mapping 확인

## 1. Schema 파일 개요

최신 RoomOS schema는 RoomOS xAPI의 command, configuration, status, event 정의를 담은 JSON 파일이다.

Top-level 구조:

```json
{
  "objects": [
    {
      "attributes": { "...": "..." },
      "id": 20462,
      "normPath": "AirPlay KeyEvent Back",
      "path": "AirPlay KeyEvent Back",
      "products": ["bandai", "barents", "davinci"],
      "type": "Command"
    }
  ]
}
```

총 object 수:

- 전체: `2,897`

타입별 개수:

- `Configuration`: `1,321`
- `Status`: `800`
- `Command`: `592`
- `Event`: `184`

공통 필드:

- `id`: schema 내부 numeric id
- `type`: `Command`, `Configuration`, `Status`, `Event`
- `path`: RoomOS xAPI path 원문
- `normPath`: 정규화된 path
- `products`: 해당 object를 지원하는 product key 목록
- `attributes`: 타입별 상세 metadata

## 2. Object 타입별 의미

### 2.1 Command

RoomOS `xCommand`에 해당한다.

예:

```text
Webex Join
Call Disconnect
Audio Volume Set
Cameras SpeakerTrack Set
Presentation Start
```

주요 `attributes`:

- `access`: 대부분 `public-api`
- `backend`: `any` 또는 일부 `onprem`
- `description`: 설명
- `params`: command argument 목록
- `privacyimpact`: `True` 또는 `False`
- `read`: command에서는 보통 빈 배열
- `role`: 실행 가능한 role
- `state_dependent`: 일부 command에 존재
- `unavailableStates`: 일부 command에 존재
- `multiline`: 일부 command에 존재

Command parameter 구조 예:

```json
{
  "name": "Output",
  "required": false,
  "default": "All",
  "description": "...",
  "valuespace": {
    "Values": ["HDMI", "Line", "Internal", "Headset", "All"],
    "description": {},
    "type": "Literal"
  }
}
```

Command domain 상위 분포:

- `Audio`: 89
- `UserInterface`: 68
- `Video`: 51
- `Cameras`: 43
- `Conference`: 39
- `Security`: 32
- `SystemUnit`: 25
- `Camera`: 23
- `Peripherals`: 23
- `Call`: 17
- `Webex`: 11

### 2.2 Configuration

RoomOS `xConfiguration`에 해당한다.

예:

```text
Audio DefaultVolume
Video Output Connector[n] MonitorRole
Cameras SpeakerTrack DefaultBehavior
RoomAnalytics PeoplePresenceDetector
```

주요 `attributes`:

- `access`: 대부분 `public-api`
- `backend`: `any` 또는 일부 `onprem`
- `default`: 기본값
- `description`: 설명
- `read`: 읽기 가능 role
- `role`: 변경 가능 role
- `valuespace`: 허용값/범위
- `include_for_extension`: 일부 `mtr`
- `cloud_visible`: 일부 존재
- `hide_value`: 일부 존재

`valuespace` 타입 분포:

- `Literal`: 926
- `Integer`: 225
- `String`: 170

Integer valuespace 예:

```json
{
  "Max": "100",
  "Min": "0",
  "Step": "100",
  "type": "Integer"
}
```

Configuration domain 상위 분포:

- `Cameras`: 304
- `Video`: 285
- `Audio`: 215
- `UserInterface`: 115
- `Network[1]`: 42
- `NetworkServices`: 41
- `Conference`: 30
- `Standby`: 24
- `UserManagement`: 21
- `Peripherals`: 19
- `Webex`: 18

### 2.3 Status

RoomOS `xStatus`에 해당한다.

예:

```text
Audio Microphones Mute
Call[n] Status
RoomAnalytics AmbientTemperature
Peripherals ConnectedDevice[n] RoomAnalytics RelativeHumidity
SystemUnit State NumberOfActiveCalls
```

주요 `attributes`:

- `access`: 대부분 `public-api`
- `backend`: `any` 또는 일부 `onprem`
- `description`: 설명
- `privacyimpact`: `True` 또는 `False`
- `role`: 읽을 수 있는 role
- `valuespace`: 값 타입/범위
- `include_for_extension`: 일부 `mtr`
- `maxOccurrence`: 일부 반복 status에 존재

`valuespace` 타입 분포:

- `Literal`: 343
- `String`: 265
- `Integer`: 192

Status domain 상위 분포:

- `Conference`: 109
- `Video`: 93
- `Audio`: 88
- `MediaChannels`: 83
- `Network[n]`: 67
- `UserInterface`: 44
- `Cameras`: 41
- `SystemUnit`: 40
- `MicrosoftTeams`: 30
- `Peripherals`: 29
- `RoomAnalytics`: 24

### 2.4 Event

RoomOS `xEvent`에 해당한다.

예:

```text
UserInterface Extensions Widget Action
Bookings Updated
Conference Presentation LocalInstance
Peripherals ConnectedDevice Added
```

주요 `attributes`:

- `access`: `public-api`
- `backend`: `any`
- `children`: event payload schema
- `read`: event 구독/읽기 role
- `role`: 대부분 빈 배열

Event domain 상위 분포:

- `UserInterface`: 44
- `Bookings`: 18
- `Conference`: 15
- `Macros`: 11
- `SystemUnit`: 9
- `Peripherals`: 8
- `Audio`: 5
- `CallTransfer`: 5

## 3. Product key 의미

각 schema object의 `products` 배열은 해당 xAPI object를 지원하는 RoomOS 제품군을 나타낸다.

예:

```json
"products": [
  "bandai",
  "barents",
  "barents_70d",
  "brooklyn",
  "davinci"
]
```

이 값들은 Cisco 내부 product key다. 사용자에게 직접 보여주기보다는 `productHelper.js` mapping을 통해 공식 제품명으로 변환해야 한다.

## 4. productHelper.js 전체 매핑

첨부 이미지의 `productHelper.js`와 실제 사이트 JS bundle에서 확인한 mapping이다.

- `bandai`: Desk Mini
- `barents`: Codec Pro
- `barents_70d`: Room 70 Dual G2
- `barents_70i`: Room 70 Panorama
- `barents_70s`: Room 70 Single G2
- `barents_82i`: Room Panorama
- `brooklyn`: Room Bar Pro
- `darling_10_55`: Board 55
- `darling_10_70`: Board 70
- `darling_15_55`: Board 55S
- `darling_15_70`: Board 70S
- `darling_15_85`: Board 85S
- `davinci`: Room Bar
- `felix_55`: Board Pro 55 G2
- `felix_75`: Board Pro 75 G2
- `helix_55`: Board Pro 55
- `helix_75`: Board Pro 75
- `havella`: Room Kit Mini
- `hopen`: Room Kit
- `millennium`: Codec EQ
- `octavio`: Desk
- `pictoris`: Desk Pro G2
- `polaris`: Desk Pro
- `spitsbergen`: Room 55
- `svea`: Codec Plus
- `svea_55d`: Room 55 Dual
- `svea_70d`: Room 70 Dual
- `svea_70s`: Room 70 Single
- `tyne`: Codec Pro G2
- `vecchio`: Navigator

## 5. 현재 schema에 실제 등장하는 product key

아래 목록은 `26.5.1 April 2026` schema의 `objects[*].products`에 실제로 등장하는 key만 정리한 것이다.

### `bandai`

- 공식 이름: Desk Mini
- Command: 417
- Configuration: 555
- Status: 679
- Event: 184
- Total: 1,835

### `barents`

- 공식 이름: Codec Pro
- Command: 467
- Configuration: 752
- Status: 751
- Event: 184
- Total: 2,154

### `barents_70d`

- 공식 이름: Room 70 Dual G2
- Command: 466
- Configuration: 731
- Status: 750
- Event: 184
- Total: 2,131

### `barents_70i`

- 공식 이름: Room 70 Panorama
- Command: 452
- Configuration: 707
- Status: 718
- Event: 184
- Total: 2,061

### `barents_70s`

- 공식 이름: Room 70 Single G2
- Command: 466
- Configuration: 731
- Status: 750
- Event: 184
- Total: 2,131

### `barents_82i`

- 공식 이름: Room Panorama
- Command: 451
- Configuration: 711
- Status: 718
- Event: 184
- Total: 2,064

### `brooklyn`

- 공식 이름: Room Bar Pro
- Command: 449
- Configuration: 873
- Status: 768
- Event: 184
- Total: 2,274

### `davinci`

- 공식 이름: Room Bar
- Command: 431
- Configuration: 616
- Status: 730
- Event: 184
- Total: 1,961

### `felix_55`

- 공식 이름: Board Pro 55 G2
- Command: 444
- Configuration: 887
- Status: 767
- Event: 184
- Total: 2,282

### `felix_75`

- 공식 이름: Board Pro 75 G2
- Command: 444
- Configuration: 887
- Status: 767
- Event: 184
- Total: 2,282

### `helix_55`

- 공식 이름: Board Pro 55
- Command: 439
- Configuration: 868
- Status: 764
- Event: 184
- Total: 2,255

### `helix_75`

- 공식 이름: Board Pro 75
- Command: 439
- Configuration: 868
- Status: 764
- Event: 184
- Total: 2,255

### `millennium`

- 공식 이름: Codec EQ
- Command: 459
- Configuration: 722
- Status: 750
- Event: 184
- Total: 2,115

### `octavio`

- 공식 이름: Desk
- Command: 417
- Configuration: 573
- Status: 680
- Event: 184
- Total: 1,854

### `polaris`

- 공식 이름: Desk Pro
- Command: 425
- Configuration: 599
- Status: 731
- Event: 184
- Total: 1,939

### `vecchio`

- 공식 이름: Navigator
- Command: 185
- Configuration: 206
- Status: 193
- Event: 184
- Total: 768

## 6. productHelper에는 있지만 현재 schema에는 없는 key

`productHelper.js`에는 있지만 `26.5.1 April 2026` schema의 `objects[*].products`에는 등장하지 않는 key들이다.

- `darling_10_55`: Board 55
- `darling_10_70`: Board 70
- `darling_15_55`: Board 55S
- `darling_15_70`: Board 70S
- `darling_15_85`: Board 85S
- `havella`: Room Kit Mini
- `hopen`: Room Kit
- `pictoris`: Desk Pro G2
- `spitsbergen`: Room 55
- `svea`: Codec Plus
- `svea_55d`: Room 55 Dual
- `svea_70d`: Room 70 Dual
- `svea_70s`: Room 70 Single
- `tyne`: Codec Pro G2

해석:

- `productHelper.js`는 사이트 전체에서 사용하는 broader product-name mapping일 가능성이 높다.
- 특정 schema 버전의 `objects[*].products`에는 모든 제품 key가 등장하지 않을 수 있다.
- capability 판단은 schema의 `products` 배열을 기준으로 해야 한다.
- 표시 이름은 `productHelper.js` mapping을 기준으로 붙이는 것이 안전하다.

## 7. Device Assistant 적용 권장 구조

제품 관련 값을 다음 세 가지로 분리해서 다루는 것이 좋다.

### 7.1 내부 schema key

```python
product_key = "davinci"
```

용도:

- schema compatibility lookup
- 지원 command/config/status/event 필터링
- product-specific capability check

### 7.2 공식 표시 이름

```python
display_name = "Room Bar"
```

용도:

- 사용자 응답
- admin page 표시
- device selector card 표시
- documentation

### 7.3 실제 Webex inventory 이름

```python
webex_display_name = "Room Bar"
```

용도:

- `/v1/devices` 결과의 실제 장치명
- target device resolution

이 세 값을 섞지 않는 것이 중요하다.

## 8. 추천 Python 매핑

현재 schema에 실제 등장하는 key 기준:

```python
ROOMOS_PRODUCT_NAMES = {
    "bandai": "Desk Mini",
    "barents": "Codec Pro",
    "barents_70d": "Room 70 Dual G2",
    "barents_70i": "Room 70 Panorama",
    "barents_70s": "Room 70 Single G2",
    "barents_82i": "Room Panorama",
    "brooklyn": "Room Bar Pro",
    "davinci": "Room Bar",
    "felix_55": "Board Pro 55 G2",
    "felix_75": "Board Pro 75 G2",
    "helix_55": "Board Pro 55",
    "helix_75": "Board Pro 75",
    "millennium": "Codec EQ",
    "octavio": "Desk",
    "polaris": "Desk Pro",
    "vecchio": "Navigator",
}
```

productHelper.js 전체 mapping 기준:

```python
ROOMOS_PRODUCT_HELPER_NAMES = {
    "bandai": "Desk Mini",
    "barents": "Codec Pro",
    "barents_70d": "Room 70 Dual G2",
    "barents_70i": "Room 70 Panorama",
    "barents_70s": "Room 70 Single G2",
    "barents_82i": "Room Panorama",
    "brooklyn": "Room Bar Pro",
    "darling_10_55": "Board 55",
    "darling_10_70": "Board 70",
    "darling_15_55": "Board 55S",
    "darling_15_70": "Board 70S",
    "darling_15_85": "Board 85S",
    "davinci": "Room Bar",
    "felix_55": "Board Pro 55 G2",
    "felix_75": "Board Pro 75 G2",
    "helix_55": "Board Pro 55",
    "helix_75": "Board Pro 75",
    "havella": "Room Kit Mini",
    "hopen": "Room Kit",
    "millennium": "Codec EQ",
    "octavio": "Desk",
    "pictoris": "Desk Pro G2",
    "polaris": "Desk Pro",
    "spitsbergen": "Room 55",
    "svea": "Codec Plus",
    "svea_55d": "Room 55 Dual",
    "svea_70d": "Room 70 Dual",
    "svea_70s": "Room 70 Single",
    "tyne": "Codec Pro G2",
    "vecchio": "Navigator",
}
```

## 9. Capability check 적용 방식

### 9.1 Command 지원 여부

예:

```text
Cameras SpeakerTrack Set
Webex Join
Video Selfview Set
Audio Volume Set
```

확인 조건:

- `type == "Command"`
- `path == "<xCommand path>"`
- target device의 `product_key`가 `products` 안에 포함되어야 함

### 9.2 Configuration 지원 여부

예:

```text
Video Output Connector[n] MonitorRole
Cameras SpeakerTrack DefaultBehavior
```

확인 조건:

- `type == "Configuration"`
- `path == "<xConfiguration path>"`
- target device의 `product_key`가 `products` 안에 포함되어야 함
- `attributes.valuespace`로 허용값 검증

### 9.3 Status 지원 여부

예:

```text
RoomAnalytics AmbientTemperature
Peripherals ConnectedDevice[n] RoomAnalytics RelativeHumidity
```

확인 조건:

- `type == "Status"`
- `path == "<xStatus path>"`
- target device의 `product_key`가 `products` 안에 포함되어야 함
- `attributes.privacyimpact == "True"`인 경우 응답/로그 노출 주의

## 10. 주의점

- schema product key는 Cisco 내부 codename이므로 사용자에게 그대로 보여주지 않는다.
- productHelper mapping은 UI 표시용이다.
- capability 판단은 schema의 `products` 배열을 기준으로 한다.
- 현재 schema에는 productHelper의 모든 key가 등장하지 않는다.
- `backend: onprem`인 object는 Webex cloud xAPI 경로에서 제한될 수 있다.
- `privacyimpact: True`인 command/status는 사용자 응답, audit log, debug log 노출 정책을 조심해야 한다.
- `valuespace`는 validation에 바로 활용할 수 있다.
- `role` / `read`는 접근 권한 판단의 참고 기준으로 활용할 수 있다.

## 11. 요약

이 schema는 RoomOS xAPI capability database로 볼 수 있다.

- `objects[*].type`은 API 종류를 나타낸다.
- `objects[*].path`는 실제 xAPI path다.
- `objects[*].products`는 지원 제품군 key다.
- `attributes.params`와 `attributes.valuespace`는 입력 검증에 활용할 수 있다.
- `productHelper.js`는 product key를 공식 표시 이름으로 바꾸는 UI mapping이다.

Device Assistant에서는 다음 원칙이 가장 안전하다.

1. 기능 지원 여부는 schema `products` 기준으로 판단한다.
2. 사용자 표시 이름은 productHelper mapping으로 변환한다.
3. Webex inventory의 실제 장치명은 별도로 관리한다.
4. command/config/status 실행 전 schema 기반 capability check를 추가한다.
