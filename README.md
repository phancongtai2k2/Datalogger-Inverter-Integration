# Datalogger Inverter — Bộ tích hợp cho Web/App

Mọi thứ cần để kết nối ứng dụng với datalogger biến tần SRNE qua MQTT: tài liệu API, ví dụ
client chạy được và bộ giả lập thiết bị. Không cần phần cứng, không cần mã nguồn firmware.

Áp dụng cho firmware datalogger **1.0.16 trở lên**.

## Có gì trong repo

| Đường dẫn | Nội dung |
|---|---|
| [docs/AI_INTEGRATION_GUIDE.md](docs/AI_INTEGRATION_GUIDE.md) | Hợp đồng API đầy đủ, viết cho AI lập trình (tiếng Anh): topic, payload, lệnh, mã ACK, quy tắc bắt buộc |
| [docs/MQTT_API.md](docs/MQTT_API.md) | Cùng nội dung cho người đọc (tiếng Việt), kèm phương pháp test |
| [examples/python/client.py](examples/python/client.py) | Ví dụ tối thiểu: dò thiết bị, gửi lệnh, chờ ACK theo `cmd_id` |
| [examples/node/client.js](examples/node/client.js) | Như trên, cho Node.js |
| [simulator/device_simulator.py](simulator/device_simulator.py) | Giả lập một thiết bị trên broker để phát triển và test |

## Bắt đầu nhanh

1. Nhận thông tin broker (host, username, password) từ người quản lý dự án. **Không commit chúng.**
2. Tạo file `.env` từ [.env.example](.env.example) và nạp vào môi trường:
   ```bash
   export MQTT_HOST=... MQTT_USER=... MQTT_PASSWORD=... MQTT_TENANT=dev
   ```
3. Chạy bộ giả lập ở một cửa sổ:
   ```bash
   pip install "paho-mqtt>=2.0"
   python simulator/device_simulator.py
   ```
4. Chạy ví dụ ở cửa sổ khác:
   ```bash
   python examples/python/client.py
   # hoặc
   cd examples/node && npm install && node client.js
   ```
   Kết quả mong đợi: in ra một ACK có `"code": 400` (ví dụ cố ý gửi tham số sai nên không đổi gì).

## Tenant: `dev` và `ggp`

Topic có dạng `solar/{tenant}/inverter/{sn}/...`.

- `dev`: dùng với bộ giả lập. Phát triển và chạy test tự động ở đây.
- `ggp`: thiết bị thật, nối với biến tần thật. Lệnh gửi vào đây **thay đổi cài đặt biến tần**.
  Chỉ dùng khi đã test xong với bộ giả lập và có người phụ trách thiết bị đồng ý.

## Bộ giả lập

```bash
python simulator/device_simulator.py --sn SIM-0002 --locked --update 1.0.99
```

| Tùy chọn | Tác dụng |
|---|---|
| `--sn` | Serial của thiết bị giả (mặc định `SIM-0001`). Chạy nhiều tiến trình với serial khác nhau để giả lập nhiều thiết bị |
| `--locked` | Biến tần giả từ chối `pv_priority: load / grid` (ACK 500 "Biến tần từ chối…"), như máy thật khi chưa nhập mật khẩu |
| `--update 1.0.99` | Báo có bản firmware mới để test luồng nâng cấp (`FIRMWARE_UPGRADE`) |

Bộ giả lập publish `status`, `telemetry` (5 giây), `battery` (20 giây), `config/state`, `firmware`,
xử lý đủ 5 lệnh và trả ACK theo đúng quy tắc trong tài liệu (kiểm tra tham số, lệnh quá 5 phút,
lệnh gửi lặp). Số liệu đo là giả, lặp theo chu kỳ 10 phút.

## Lưu ý khi viết code

Đọc mục **"Rules you must follow"** trong
[docs/AI_INTEGRATION_GUIDE.md](docs/AI_INTEGRATION_GUIDE.md). Quan trọng nhất:

- Mỗi lệnh một `cmd_id` mới; ghép ACK theo `cmd_id`.
- Sau ACK 200, hiển thị theo `up/config/state`, không theo giá trị vừa gửi.
- Trường không có trong payload nghĩa là "không rõ", không phải 0.
- Không gán cứng `sn`, tenant hay thông tin đăng nhập.
- Hỏi người dùng trước khi bật chế độ phát điện lên lưới và trước khi nâng cấp firmware.
