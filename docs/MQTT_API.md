# MQTT API — Datalogger biến tần SRNE (chuẩn GGP.Solar)

Tài liệu cho đội Web App / Backend. Áp dụng cho firmware datalogger **từ 1.0.16**.
Mọi ví dụ payload bên dưới là dữ liệu thật lấy từ thiết bị.

## 1. Kết nối

| | |
|---|---|
| Giao thức | MQTT 3.1.1 qua TLS (port 8883) |
| Broker / tài khoản | Cấp riêng, không ghi trong tài liệu này |
| Định dạng | JSON UTF-8, không khoảng trắng thừa |
| Thời gian (`ts`) | Unix timestamp, giây, UTC |

## 2. Cấu trúc topic

```
solar/{tenant}/inverter/{sn}/up/...     thiết bị -> cloud
solar/{tenant}/inverter/{sn}/down/...   cloud -> thiết bị
```

- `{tenant}`: mặc định `ggp`.
- `{sn}`: **serial number của biến tần** (đọc từ biến tần), ví dụ `INV-EXAMPLE-0001`.
  Khi datalogger chưa đọc được biến tần lần nào, nó tạm dùng Device ID của datalogger
  (ví dụ `datalogger_01`); ngay khi đọc được SN, nó chuyển sang topic theo SN.
  Web App nên subscribe `solar/{tenant}/inverter/+/up/#` và lấy `sn` trong payload.

| Topic (sau `solar/{tenant}/inverter/{sn}/`) | Hướng | Retain | Khi nào gửi |
|---|---|---|---|
| `up/status` | lên | có | Khi kết nối, khi thông tin biến tần thay đổi; `offline` khi mất kết nối |
| `up/telemetry` | lên | không | Mỗi 5 giây (khi biến tần trả lời) |
| `up/battery` | lên | không | Mỗi 20 giây |
| `up/alarm` | lên | không | Khi một mã lỗi xuất hiện hoặc hết |
| `up/config/state` | lên | có | Sau khi kết nối và sau mỗi lệnh thay đổi cài đặt |
| `up/firmware` | lên | có | Khi trạng thái firmware / bản cập nhật thay đổi |
| `up/command/ack` | lên | không | Trả lời cho từng lệnh |
| `down/command` | xuống | - | Web App gửi lệnh |

Topic **retained** luôn trả về bản tin mới nhất ngay khi subscribe, dùng để hiển thị trạng thái
hiện tại mà không cần chờ.

Trường nào thiết bị không đọc được thì **không có trong payload** (không gửi số 0 giả).
Web App cần xử lý trường thiếu.

## 3. Bản tin thiết bị gửi lên

### 3.1 `up/status` — trạng thái kết nối
```json
{"sn":"INV-EXAMPLE-0001","state":"online","ts":1790935526,"model":"SRNE Hybrid Inverter M39","fw_ver":"V2.85","ip_addr":"192.168.1.50","signal_rssi":-32,"logger_fw":"1.0.14","inverter_comm":"ok"}
```
Mất kết nối đột ngột (mất điện, rớt mạng), broker tự phát:
```json
{"sn":"INV-EXAMPLE-0001","state":"offline","ts":1790935526,"reason":"connection_lost"}
```

| Trường | Ý nghĩa |
|---|---|
| `state` | `online` / `offline` |
| `ts` | Với `offline`: là thời điểm kết nối gần nhất, **không phải** lúc mất kết nối |
| `reason` | `connection_lost` (mất kết nối), `sn_changed` / `reconfigure` (thiết bị chủ động đổi topic) |
| `model`, `fw_ver` | Model và firmware của **biến tần** |
| `logger_fw` | Firmware của datalogger |
| `inverter_comm` | `ok`: đang đọc được biến tần · `no_response`: biến tần không trả lời RS485 |
| `ip_addr`, `signal_rssi` | IP nội bộ và cường độ WiFi (dBm) của datalogger |

### 3.2 `up/telemetry` — đo lường tức thời (5 giây)
```json
{"sn":"INV-EXAMPLE-0001","ts":1790936027,"inv_status":1,"inv_temp":34.1,
 "pv":{"v_pv1":0,"i_pv1":0,"p_pv1":0,"v_pv2":0,"i_pv2":0,"p_pv2":0,"p_total":0},
 "grid":{"v_ac":230,"i_ac":0,"freq":50.08,"p_active":0,"p_direction":"idle"},
 "load":{"v_out":0,"i_out":0,"p_active":0,"freq":0},
 "battery":{"p_flow":-0.4,"p_direction":"idle","soc":0},
 "energy":{"yield_today_kwh":0,"yield_total_kwh":0,"load_today_kwh":0,"grid_export_today_kwh":0}}
```

| Trường | Đơn vị | Ghi chú |
|---|---|---|
| `inv_status` | - | 0 khởi tạo · 1 chờ (standby) · 2 chạy điện lưới · 3 chạy inverter |
| `inv_temp` | °C | Nhiệt độ tản nhiệt |
| `pv.v_pv1/2`, `pv.i_pv1/2`, `pv.p_pv1/2`, `pv.p_total` | V, A, W | 2 chuỗi PV và tổng |
| `grid.v_ac`, `grid.i_ac`, `grid.freq` | V, A, Hz | Lưới |
| `grid.p_active` | W | **Âm = phát lên lưới (export), dương = mua từ lưới (import)** |
| `grid.p_direction` | - | `export` / `import` / `idle` |
| `load.v_out`, `load.i_out`, `load.p_active`, `load.freq` | V, A, W, Hz | Ngõ ra tải |
| `battery.p_flow` | W | **Âm = đang sạc, dương = đang xả** |
| `battery.p_direction` | - | `charging` (< -10 W) / `discharging` (> 10 W) / `idle` |
| `battery.soc` | % | |
| `energy.yield_today_kwh`, `yield_total_kwh` | kWh | Sản lượng PV hôm nay / tích lũy |
| `energy.load_today_kwh` | kWh | Tải tiêu thụ hôm nay |
| `energy.grid_export_today_kwh` | kWh | Phát lên lưới hôm nay |
| `energy.grid_import_today_kwh` | kWh | Mua từ lưới hôm nay — **không có trên một số model** |

Không có bản tin telemetry khi biến tần không trả lời (xem `inverter_comm` ở `up/status`).

### 3.3 `up/battery` — chi tiết pin (20 giây)
```json
{"sn":"INV-EXAMPLE-0001","bms_sn":"BAT-INV-EXAMPLE-0001-01","ts":1790936022,"model":"Battery","soc":0,"soh":0,"voltage":0.7,"current":-0.6,"power_w":0.4,"status":"charging","temp_cells_avg":-35,"temp_bms":0,"cycle_count":0,"capacity_ah_remaining":0,"capacity_ah_nominal":0}
```
(Ví dụ trên là lúc **chưa đấu pin**: điện áp gần 0, nhiệt độ −35 là cảm biến hở.)

| Trường | Đơn vị | Ghi chú |
|---|---|---|
| `soc`, `soh` | % | |
| `voltage` | V | |
| `current` | A | **Âm = sạc, dương = xả** |
| `power_w` | W | Luôn dương (= điện áp × \|dòng\|) |
| `status` | - | `charging` (< -0.5 A) / `discharging` (> 0.5 A) / `standby` |
| `est_time_remaining_min` | phút | Thời gian dự kiến sạc đầy / xả tới mức dự phòng; có khi biết dung lượng danh định |
| `temp_cells_avg`, `temp_bms` | °C | |
| `cycle_count` | lần | |
| `capacity_ah_remaining`, `capacity_ah_nominal` | Ah | |
| `bms_sn`, `model` | - | Tên BMS nếu có, nếu không là `BAT-{sn}-01` / `Battery` |

### 3.4 `up/alarm` — cảnh báo
```json
{"alarm_id":"ALM-20260926-004","sn":"INV-HN-001","ts":1790413164,"event_state":"triggered","error_code":"F024","severity":"critical","title":"Mất kết nối lưới điện","description":"Inverter chuyển sang cấp điện từ pin.","data_snapshot":{"grid_v":224.5,"battery_soc":76,"load_w":2500}}
```

| Trường | Ghi chú |
|---|---|
| `event_state` | `triggered` (lỗi xuất hiện) / `cleared` (lỗi hết) — mỗi sự kiện một bản tin |
| `error_code` | `F` + 3 chữ số mã lỗi của biến tần |
| `severity` | `critical` / `warning` / `info` |
| `title`, `description` | Tiếng Việt. Mã chưa có trong bảng tra: nội dung chung "Lỗi biến tần Fxxx" |
| `alarm_id` | `ALM-YYYYMMDD-NNN`, duy nhất theo ngày |
| `data_snapshot` | Điện áp lưới, SOC, công suất tải lúc xảy ra |

### 3.5 `up/config/state` — cấu hình đang chạy trên biến tần
```json
{"sn":"INV-EXAMPLE-0001","ts":1790935920,"work_mode":"self_consumption",
 "grid_mode":"limit_ups_load","pv_priority":"load","battery_mode":"ups_load","grid_charging":[true,true,true],
 "zero_export":{"enabled":true,"limit_export_w":20},
 "charge_schedule":{"enabled":false,"start_time":"00:00","end_time":"00:00","charge_current_limit_a":60,"charge_power_w":3300,"stop_soc":100,"grid_charge":true,
   "periods":[{"period":1,"start_time":"00:00","end_time":"00:00","charge_power_w":3300,"stop_soc":100,"grid_charge":true},
              {"period":2,"start_time":"00:00","end_time":"00:00","charge_power_w":3300,"stop_soc":100,"grid_charge":true},
              {"period":3,"start_time":"00:00","end_time":"00:00","charge_power_w":3300,"stop_soc":100,"grid_charge":true}]},
 "battery_reserve_soc":10}
```

| Trường | Giá trị | Màn hình biến tần |
|---|---|---|
| `grid_mode` | `on_grid` · `limit_ups_load` · `limit_home_load` · `ac_coupling` | Hybrid grid mode |
| `pv_priority` | `load` · `charging` · `grid` | PV energy manage |
| `battery_mode` | `standby` · `ups_load` · `home_load` · `grid_sell` | Battery energy manage |
| `grid_charging` | `[khung1, khung2, khung3]` | Grid charging enable |
| `work_mode` | `self_consumption` · `grid_connected` · `battery_priority` · `off_grid` · `ac_coupling` | Tóm tắt (tương thích cũ) |
| `zero_export.enabled` | bool | Đang ở chế độ chống phát ngược |
| `zero_export.limit_export_w` | W | Công suất bù chống phát ngược (0–500) |
| `charge_schedule.enabled` | bool | Bật sạc theo lịch |
| `charge_schedule.periods[]` | 3 khung | Giờ, công suất sạc tối đa (W), SOC dừng sạc, sạc lưới |
| `charge_schedule.charge_current_limit_a` | A | Dòng sạc từ lưới (chung) |
| `charge_schedule.start_time/end_time/charge_power_w/stop_soc/grid_charge` | - | Lặp lại thông số khung 1 |
| `battery_reserve_soc` | % | SOC dừng xả pin |

### 3.6 `up/firmware` — phiên bản và bản cập nhật
```json
{"sn":"INV-EXAMPLE-0001","current_version":"1.0.14","latest_version":"1.0.14","update_available":false,"state":"idle","progress":0,"last_check":1790935492,"last_result":"updated to 1.0.14, health check passed","ts":1790935522}
```

| Trường | Ghi chú |
|---|---|
| `current_version` / `latest_version` | Bản đang chạy / bản mới nhất trên server |
| `update_available` | `true` khi có bản mới hơn → hiện nút nâng cấp cho người dùng |
| `state` | `idle` · `checking` · `installing` · `downloading` · `rebooting` · `verifying` |
| `progress` | 0–100 (%) khi đang tải, bước 10 |
| `last_result` | Kết quả lần kiểm tra / cài gần nhất (tiếng Anh, để hiển thị kỹ thuật) |
| `failed_version` | Có khi một bản từng cài lỗi và đã tự quay về bản cũ |

Thiết bị tự kiểm tra bản mới khi khởi động và lúc 00:00 hằng đêm. **Không tự cài**: chỉ cài khi
nhận lệnh `FIRMWARE_UPGRADE`.

## 4. Lệnh gửi xuống — `down/command`

```json
{"cmd_id":"<duy nhất>","action":"<TÊN_LỆNH>","ts":1790936000,"params":{...}}
```

| Trường | Bắt buộc | Ghi chú |
|---|---|---|
| `cmd_id` | có | Tối đa 64 ký tự. **Mỗi lệnh một `cmd_id` mới** (nên dùng UUID) |
| `action` | có | Xem bảng dưới |
| `ts` | không | Nếu có: lệnh cũ hơn **5 phút** bị từ chối (408). Nên gửi để tránh lệnh tồn bị chạy muộn |
| `params` | tùy lệnh | |

Gửi lại đúng một message (cùng `cmd_id`, cùng nội dung): thiết bị trả lại ACK cũ, **không thực thi lần hai**.

### 4.1 `SET_WORK_MODE`
```json
{"cmd_id":"..","action":"SET_WORK_MODE","params":{"grid_mode":"limit_home_load","pv_priority":"charging","battery_mode":"home_load","grid_charging":[true,false,true]}}
```
Gửi một hoặc nhiều trường (xem bảng giá trị ở mục 3.5). `grid_charging` nhận `true`/`false`
(cả 3 khung) hoặc mảng 3 phần tử.
Kiểu cũ vẫn dùng được: `{"mode":"self_consumption" | "grid_connected" | "battery_priority"}`.

> `on_grid`, `ac_coupling`, `grid_sell` cho phép phát điện lên lưới.

### 4.2 `SET_CHARGE_SCHEDULE`
Một khung (khung 1):
```json
{"cmd_id":"..","action":"SET_CHARGE_SCHEDULE","params":{"enabled":true,"start_time":"22:00","end_time":"04:00","charge_power_w":3000,"stop_soc":100,"charge_current_a":30}}
```
Nhiều khung:
```json
{"cmd_id":"..","action":"SET_CHARGE_SCHEDULE","params":{"enabled":true,"periods":[
  {"start_time":"22:00","end_time":"04:00","charge_power_w":3000,"stop_soc":90},
  {"start_time":"12:00","end_time":"14:00","charge_power_w":1500,"grid_charging":false},
  {"period":3,"start_time":"00:00","end_time":"00:00"}]}}
```

| Tham số | Bắt buộc | Khoảng | Ghi chú |
|---|---|---|---|
| `enabled` | có | bool | Bật/tắt sạc theo lịch (chung cho 3 khung) |
| `start_time`, `end_time` | khi bật | `HH:MM` | Phải gửi cả hai. `00:00`–`00:00` = tắt khung đó |
| `charge_power_w` | không | 0–12000 | Công suất sạc tối đa của khung |
| `stop_soc` | không | 0–100 | Dừng sạc khi SOC đạt mức này |
| `grid_charging` (trong khung) | không | bool | Mặc định: tự bật cho khung có giờ khi `enabled` |
| `charge_current_a` | không | (0, 400] | Dòng sạc từ lưới, chung |
| `periods` | không | 1–3 phần tử | Vị trí trong mảng = số khung, hoặc chỉ định `"period": 1..3`. Khung không gửi giữ nguyên |

### 4.3 `SET_GRID_PARAMETERS`
```json
{"cmd_id":"..","action":"SET_GRID_PARAMETERS","params":{"zero_export_enabled":true,"max_export_power_w":20}}
```
| Tham số | Ghi chú |
|---|---|
| `zero_export_enabled` | `true`: chống phát ngược (mặc định theo tải nhà; `"zero_export_mode":"ups_load"` để theo tải UPS). `false`: cho phép phát lên lưới |
| `max_export_power_w` | 0–500 W |

Cần ít nhất một trong hai tham số.

### 4.4 `FIRMWARE_CHECK` / `FIRMWARE_UPGRADE`
```json
{"cmd_id":"..","action":"FIRMWARE_CHECK","params":{}}
{"cmd_id":"..","action":"FIRMWARE_UPGRADE","params":{"version":"1.0.15"}}
```
`version` phải đúng bằng `latest_version` trong `up/firmware`.

## 5. Trả lời lệnh — `up/command/ack`
```json
{"cmd_id":"DOC-1","sn":"INV-EXAMPLE-0001","action":"SET_WORK_MODE","ts":1790936003,"success":false,"code":400,"message":"params.grid_mode không hợp lệ: 'turbo' (on_grid | limit_ups_load | limit_home_load | ac_coupling)"}
```

| `code` | Ý nghĩa | Web App nên làm |
|---|---|---|
| 200 | Thành công (đã ghi xuống biến tần) | Chờ `up/config/state` mới để cập nhật giao diện |
| 400 | Sai tham số / action không hỗ trợ / version không hợp lệ | Hiện `message` |
| 408 | Lệnh quá 5 phút | Gửi lại với `ts` mới |
| 409 | Thiết bị đang bận, hoặc server không còn bản firmware đó | Thử lại sau |
| 422 | File firmware bị từ chối | Báo kỹ thuật |
| 500 | Biến tần không trả lời (`message` có `TIMEOUT`, thử lại được); hoặc biến tần **từ chối giá trị** (`message` bắt đầu bằng "Biến tần từ chối": không cho phép ở trạng thái hiện tại, thử lại không có tác dụng); hoặc lỗi mạng khi tải firmware | Hiện `message` |
| 503 | Hàng đợi lệnh đầy | Thử lại sau |

`message` bằng tiếng Việt, có thể hiển thị trực tiếp cho người dùng.

Thời gian chờ ACK:
- Lệnh cài đặt: thường dưới 2 giây; đặt timeout **15 giây**.
- `FIRMWARE_UPGRADE`: ACK chỉ về **sau khi cài xong** (khoảng 30 giây) hoặc khi lỗi; đặt timeout **5 phút**.

Lệnh gồm nhiều thanh ghi được ghi lần lượt và **dừng ở lỗi đầu tiên**; khi đó ACK báo 500 và
`up/config/state` phản ánh phần đã ghi được.

## 6. Luồng xử lý gợi ý

**Đổi cài đặt**
1. Hiển thị giá trị từ `up/config/state` (retained).
2. Người dùng đổi → gửi lệnh với `cmd_id` mới, `ts` hiện tại.
3. Chờ `up/command/ack` có cùng `cmd_id`.
4. `code` 200 → chờ `up/config/state` mới và hiển thị theo đó (đây là giá trị đọc lại từ biến tần).

**Nâng cấp firmware**
1. `up/firmware` có `update_available: true` → hiện nút "Nâng cấp lên `latest_version`".
2. Người dùng xác nhận → gửi `FIRMWARE_UPGRADE` với `version = latest_version`.
3. Hiển thị `progress` từ `up/firmware` (`state: downloading`).
4. ACK 200 → thiết bị khởi động lại; `up/status` có thể `offline` rồi `online`.
5. `up/firmware.current_version` = bản mới. Sau khoảng 1 phút `last_result` có "health check passed".
   Nếu bản mới lỗi, thiết bị tự quay về bản cũ và báo `failed_version`.

**Thiết bị offline**: `up/status.state = offline`. Lệnh gửi trong lúc này được broker giữ lại
(phiên MQTT được duy trì) và giao khi thiết bị online lại; lệnh có `ts` cũ hơn 5 phút sẽ bị từ chối.

## 7. Phương pháp test (HiveMQ Web Client hoặc MQTTX)

**Chuẩn bị**
1. Kết nối broker bằng tài khoản được cấp.
2. Subscribe `solar/ggp/inverter/+/up/#`.
3. Lấy `sn` từ bản tin `up/status` → topic lệnh là `solar/ggp/inverter/{sn}/down/command`.
4. Ghi lại `up/config/state` hiện tại để trả về sau khi test.

**Test đọc**

| Kiểm tra | Mong đợi |
|---|---|
| `up/status` | `state: online`, `inverter_comm: ok` |
| `up/telemetry` | Có bản tin mỗi 5 giây; số liệu khớp màn hình biến tần |
| `up/battery` | Có bản tin mỗi 20 giây |
| `up/config/state` | Khớp màn hình Work mode và lịch sạc |
| `up/firmware` | `current_version` đúng |

**Test lệnh** (mỗi lần đổi `cmd_id`; kiểm tra ACK 200, `up/config/state` mới, và màn hình biến tần)

| # | Payload gửi `down/command` | Mong đợi |
|---|---|---|
| 1 | `{"cmd_id":"T-01","action":"SET_WORK_MODE","params":{"grid_mode":"limit_home_load"}}` | `grid_mode: limit_home_load` |
| 2 | `{"cmd_id":"T-02","action":"SET_WORK_MODE","params":{"pv_priority":"charging"}}` | `pv_priority: charging` |
| 3 | `{"cmd_id":"T-03","action":"SET_WORK_MODE","params":{"battery_mode":"standby"}}` | `battery_mode: standby` |
| 4 | `{"cmd_id":"T-04","action":"SET_WORK_MODE","params":{"grid_charging":[true,false,false]}}` | `grid_charging: [true,false,false]` |
| 5 | `{"cmd_id":"T-05","action":"SET_CHARGE_SCHEDULE","params":{"enabled":true,"start_time":"22:00","end_time":"04:00","charge_power_w":3000}}` | Khung 1: 22:00–04:00, 3000 W, bật |
| 6 | `{"cmd_id":"T-06","action":"SET_GRID_PARAMETERS","params":{"max_export_power_w":50}}` | `limit_export_w: 50` |
| 7 | `{"cmd_id":"T-07","action":"FIRMWARE_CHECK","params":{}}` | ACK 200; `up/firmware.last_check` mới |

**Test bắt lỗi** (không thay đổi biến tần)

| Payload | ACK mong đợi |
|---|---|
| `{"cmd_id":"T-E1","action":"SET_WORK_MODE","params":{"grid_mode":"turbo"}}` | 400 |
| `{"cmd_id":"T-E2","action":"SET_WORK_MODE","params":{"grid_charging":[true]}}` | 400 |
| `{"cmd_id":"T-E3","action":"SET_CHARGE_SCHEDULE","params":{"enabled":true,"start_time":"25:00","end_time":"04:00"}}` | 400 |
| `{"cmd_id":"T-E4","action":"SET_CHARGE_SCHEDULE","params":{"enabled":true,"start_time":"22:00","end_time":"04:00","charge_power_w":13000}}` | 400 |
| `{"cmd_id":"T-E5","action":"SET_GRID_PARAMETERS","params":{"max_export_power_w":900}}` | 400 |
| `{"cmd_id":"T-E6","action":"UNKNOWN","params":{}}` | 400 |
| `{"cmd_id":"T-E7","action":"SET_WORK_MODE","ts":1727280200,"params":{"pv_priority":"load"}}` | 408 |
| `{"cmd_id":"T-E8","action":"FIRMWARE_UPGRADE","params":{"version":"1.0.1"}}` | 400 |
| Gửi lại y hệt T-E1 | Nhận lại đúng ACK cũ |

**Trả về trạng thái ban đầu** (thay giá trị theo bản ghi ở bước chuẩn bị)
```json
{"cmd_id":"T-90","action":"SET_WORK_MODE","params":{"grid_mode":"limit_ups_load","pv_priority":"load","battery_mode":"ups_load","grid_charging":true}}
{"cmd_id":"T-91","action":"SET_CHARGE_SCHEDULE","params":{"enabled":false,"start_time":"00:00","end_time":"00:00","charge_power_w":3300,"charge_current_a":60}}
{"cmd_id":"T-92","action":"SET_GRID_PARAMETERS","params":{"max_export_power_w":20}}
```

**Mật khẩu biến tần**: một số cài đặt (ví dụ `pv_priority: load / grid`) cần mật khẩu người dùng của
biến tần. Datalogger tự nhập khi đã được cấu hình (Web UI của datalogger → Modbus → Mật khẩu biến tần).
Nếu ACK 500 có chữ "mật khẩu biến tần": cần cấu hình hoặc sửa mật khẩu trên datalogger; Web App
không gửi mật khẩu qua MQTT.

**Không nhận được ACK?**
- Sai `{sn}` trong topic (thiết bị chỉ nghe topic theo SN hiện tại của nó — xem `up/status`).
- Thiết bị offline (`up/status.state`).
- ACK 500 kèm `TIMEOUT`: biến tần không trả lời datalogger (kiểm tra dây RS485 / nguồn biến tần).

## 8. Giới hạn hiện tại
- Bản tin gửi lên dùng QoS 0 (trên kết nối TCP/TLS); `up/status` offline (LWT) và việc nhận lệnh dùng QoS 1.
- `grid_import_today_kwh` và thông tin BMS chi tiết không có trên một số model biến tần.
- Bảng mô tả mã lỗi (`up/alarm`) mới có các mã F001, F004, F014, F024, F058; mã khác dùng nội dung chung.
