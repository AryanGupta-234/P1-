from sentinel.advanced import _lhm_sensor_result


def test_lhm_inventory_preserves_cpu_gpu_clocks_power_voltage_and_load():
    rows = [
        {"Name": "CPU Package", "Parent": "Intel Core i5-12500H", "SensorType": "Temperature", "Value": 63.5, "Identifier": "/intelcpu/0/temperature/0"},
        {"Name": "CPU Core #1", "Parent": "Intel Core i5-12500H", "SensorType": "Temperature", "Value": 61.0},
        {"Name": "Core Clock", "Parent": "Intel Core i5-12500H", "SensorType": "Clock", "Value": 3200},
        {"Name": "CPU Package", "Parent": "Intel Core i5-12500H", "SensorType": "Power", "Value": 22.4},
        {"Name": "Core Voltage", "Parent": "Intel Core i5-12500H", "SensorType": "Voltage", "Value": 1.08},
        {"Name": "CPU Total", "Parent": "Intel Core i5-12500H", "SensorType": "Load", "Value": 42},
        {"Name": "GPU Core", "Parent": "NVIDIA GeForce RTX", "SensorType": "Temperature", "Value": 55},
        {"Name": "GPU Clock", "Parent": "NVIDIA GeForce RTX", "SensorType": "Clock", "Value": 1800},
        {"Name": "GPU Power", "Parent": "NVIDIA GeForce RTX", "SensorType": "Power", "Value": 45},
        {"Name": "GPU Voltage", "Parent": "NVIDIA GeForce RTX", "SensorType": "Voltage", "Value": 0.91},
        {"Name": "GPU Core", "Parent": "NVIDIA GeForce RTX", "SensorType": "Load", "Value": 73},
        {"Name": "System Fan #1", "Parent": "ASUS Embedded Controller", "SensorType": "Fan", "Value": 0},
    ]
    result = _lhm_sensor_result(rows, "LibreHardwareMonitor", "loopback REST", "http://127.0.0.1:8085/data.json")
    assert result["available"] is True
    assert result["cpu_temperatures"][0]["unit"] == "°C"
    assert result["per_core_temperatures"][0]["name"] == "CPU Core #1"
    assert result["cpu_clocks"][0]["unit"] == "MHz"
    assert result["cpu_power"][0]["unit"] == "W"
    assert result["cpu_voltage"][0]["unit"] == "V"
    assert result["cpu_load"][0]["unit"] == "%"
    assert result["gpu_temperatures"][0]["device_class"] == "GPU"
    assert result["gpu_clocks"][0]["value"] == 1800
    assert result["gpu_power"][0]["value"] == 45
    assert result["gpu_voltage"][0]["value"] == 0.91
    assert result["gpu_load"][0]["value"] == 73
    assert result["fan_rpm"][0]["value"] == 0
    assert len(result["sensors"]) == 12
