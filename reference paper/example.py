import requests
import time
import json
from requests.auth import HTTPBasicAuth
import serial
import ctypes
from ctypes import byref, c_int, c_double
import pandas as pd

# Disable SSL warnings for self-signed certificates
requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)

def send_command(ser, command):
    ser.write((command + '\r').encode('ascii'))
    time.sleep(0.1)
    response = ser.read_until(b'/')
    print(f"Sent: {command} | Response: {response.decode('ascii').strip()}")

def control_pumps_and_measure_spectrum(
        percent_pump1, percent_pump2, percent_pump3, percent_pump4,
        percent_pump5, percent_pump6, percent_pump7,
        method_index=0):

    # Microwave API configuration
    host = 'YOUR_IP'
    port = 'XXXX'
    base_url = f'https://{host}:{port}/api'
    username = 'YOUR_USERNAME'
    password = 'YOUR_PASSWORD'

    # Authentication to get Bearer Token
    auth_response = requests.get(f'{base_url}/auth', auth=HTTPBasicAuth(username, password), verify=False)
    if auth_response.status_code == 200:
        token = auth_response.json()['token']
        headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json'}
        print('Authentication successful, token acquired.')
    else:
        print('Error during authentication:', auth_response.status_code, auth_response.text)
        return

    # Get microwave method list
    methods_response = requests.get(f'{base_url}/methods', headers=headers, verify=False)
    if methods_response.status_code == 200:
        methods = methods_response.json()
        print('Available methods:', methods)
    else:
        print('Error fetching methods:', methods_response.status_code, methods_response.text)
        return

    # Sends syringe pump commands
    def send_commands(port, commands):
        try:
            ser = serial.Serial(
                port=port,
                baudrate=9600,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=1
            )
            for command in commands:
                ser.write((command + '\r').encode('ascii'))
                response = ser.read(100)
                print(f'Sent: {command.strip()} | Response:', response.decode('ascii').strip())

        except Exception as e:
            print("Serial error:", e)
        finally:
            try:
                if ser.is_open:
                    ser.close()
            except:
                pass

    # Prepare syringe pump commands
    def prepare_commands(address, volume, direction='counterclockwise'):
        direction_command = f'{address}J'
        return [
            f'@{address}',
            f'{address}G',
            direction_command,
            f'{address}xP00000005',
            f'{address}v{volume}',
            f'{address}H',
        ]

    def stop_pump_command(address):
        return [f'{address}I']

    port1 = 'COM4'
    port2 = 'COM5'

    total_volume = 10000

    volume_pump1 = f'{int(total_volume * percent_pump1 / 100)}+0'
    volume_pump2 = f'{int(total_volume * percent_pump2 / 100)}+0'
    volume_pump3 = f'{int(total_volume * percent_pump3 / 100)}+0'
    volume_pump4 = f'{int(total_volume * percent_pump4 / 100)}+0'
    volume_pump5 = f'{int(total_volume * percent_pump5 / 100)}+0'
    volume_pump6 = f'{int(total_volume * percent_pump6 / 100)}+0'
    volume_pump8 = f'{int(total_volume * percent_pump8 / 100)}+0'

    pump_params = [
        {'port': port1, 'address': 1, 'volume': volume_pump1},
        {'port': port1, 'address': 2, 'volume': volume_pump2},
        {'port': port1, 'address': 3, 'volume': volume_pump3},
        {'port': port1, 'address': 4, 'volume': volume_pump4},
        {'port': port2, 'address': 1, 'volume': volume_pump5},
        {'port': port2, 'address': 2, 'volume': volume_pump6},
        {'port': port2, 'address': 4, 'volume': volume_pump8}
    ]

    def run_pump(pump_params):
        commands = prepare_commands(pump_params['address'], pump_params['volume'])
        send_commands(pump_params['port'], commands)
        time.sleep(5)
        send_commands(pump_params['port'], stop_pump_command(pump_params['address']))

    print("Starting syringe pumps...")
    for pump in pump_params:
        run_pump(pump)

    # Queue selected microwave method
    if methods:
        if method_index < 0 or method_index >= len(methods):
            print(f"Invalid method_index: {method_index}")
            print(f"Valid range: 0 to {len(methods)-1}")
            return

        selected_method_id = methods[method_index]['id']
        print(f"Selected method index: {method_index}, ID: {selected_method_id}")

        queue_response = requests.post(f'{base_url}/queue/{selected_method_id}', headers=headers, verify=False)
        if queue_response.status_code != 200:
            print("Error queuing method.")
            return
    else:
        print("No microwave methods available.")
        return

    start_response = requests.post(f'{base_url}/run/start', headers=headers, verify=False)
    if start_response.status_code == 200:
        print("Microwave run started.")
    else:
        print("Run start failed.")
        return

    while True:
        status_response = requests.get(f'{base_url}/status', headers=headers, verify=False)
        if status_response.status_code == 200:
            status = status_response.json()
            run_state = status['methodRunner']['runState']
            print(f"Microwave running... State {run_state}")
            if run_state == 0:
                print("Microwave cycle completed.")
                break
        time.sleep(5)

    requests.post(f'{base_url}/queue/clear', headers=headers, verify=False)
    print("Queue cleared.")

    # Run syringe pump channel 1 10mL
    def run_channel_1():
        commands = ['@1', '1G', '1J', '1v10000+0', '1H']
        send_commands('COM4', commands)
        time.sleep(60)

    # HPLC 10mL injection
    def run_hplc_10ml():
        com_port = 'COM4'
        flow_rate_ml_min = 20.0
        volume_ml = 10.0
        run_time_sec = volume_ml / flow_rate_ml_min * 60

        try:
            with serial.Serial(com_port, baudrate=9600, timeout=1) as ser:
                flow_command = f"FI{int(flow_rate_ml_min * 1000):05d}"
                send_command(ser, flow_command)
                send_command(ser, "RU")
                print("HPLC running...")
                time.sleep(run_time_sec)
                send_command(ser, "ST")
                print("HPLC injection complete.")
        except serial.SerialException as e:
            print(f"HPLC Error: {e}")

    # Spectrometer measurement
    def measure_spectrum():
        dll_path = r'C:\Users\RW304\Desktop\spectrum\SDK\SpecDLL.dll'
        specDLL = ctypes.CDLL(dll_path)

        class DeviceInfo(ctypes.Structure):
            _fields_ = [("ID", c_int), ("type", c_int), ("serial", ctypes.c_char * 9)]

        specDLL.GetXData.restype = ctypes.POINTER(c_double)
        specDLL.GetYData.restype = ctypes.POINTER(c_int)
        specDLL.GetEndAddress.restype = c_int

        devices = (DeviceInfo * 10)()
        devices_count = c_int()
        specDLL.ScanDevices(byref(devices), byref(devices_count))

        if devices_count.value > 0:
            handle = specDLL.Connect(devices[0].ID)
            if handle != -1:
                x_data_ptr = specDLL.GetXData(handle)
                x_data = [x_data_ptr[i] for i in range(3648)]
                end_address = specDLL.GetEndAddress(handle)

                y_data_ptr = specDLL.GetYData(end_address, handle)
                y_data = [y_data_ptr[i] for i in range(3648)]

                df = pd.DataFrame({'Wavelength (nm)': x_data, 'Intensity': y_data})
                df = df[df['Wavelength (nm)'] != 0]
                df.to_excel('spectral_data.xlsx', index=False)
                print("Spectrum saved.")

    print("Running channel 1...")
    run_channel_1()
    run_hplc_10ml()
    measure_spectrum()

# Example call with method selection
control_pumps_and_measure_spectrum(
    12.5, 12.5, 12.5, 12.5, 12.5, 12.5, 12.5,
    method_index=2
)

def run_channel1_and_hplc_20ml(
        syringe_port='COM4',
        hplc_port='COM4',
        hplc_flow_rate_ml_min=20.0,
        comment='ODE'):
    """
    Run syringe pump channel 1 to inject 20 mL (log comment included),
    then run HPLC pump to inject 20 mL at the given flow rate.

    Args:
        syringe_port (str): Serial port for the syringe pump (e.g., 'COM4').
        hplc_port (str): Serial port for the HPLC pump (e.g., 'COM4').
        hplc_flow_rate_ml_min (float): HPLC flow rate in mL/min (default 20.0).
        comment (str): Tag/comment to print in logs (default 'ODE').
    """
    # ---------- 1) Syringe pump CH1: 20 mL ----------
    print(f"[{comment}] Syringe CH1 → 20 mL start.")
    syringe_cmds = [
        '@1',          # Select address 1
        '1G',          # Set mode (device-specific)
        '1J',          # Direction: counterclockwise
        '1v20000+0',   # Volume: 20 mL = 20000 µL
        '1H'           # Start
    ]
    send_commands(syringe_port, syringe_cmds)

    # Optional wait: scale from your previous 10 mL → 60 s; here 20 mL → 120 s
    # If your pump auto-stops by volume, you can shorten or remove this sleep.
    time.sleep(120)
    send_commands(syringe_port, ['1I'])  # Stop CH1
    print(f"[{comment}] Syringe CH1 → 20 mL done.")

    # ---------- 2) HPLC pump: 20 mL ----------
    print(f"[{comment}] HPLC → 20 mL start.")
    volume_ml = 20.0
    run_time_sec = volume_ml / hplc_flow_rate_ml_min * 60.0  # e.g., 20/20 mL/min = 60 s

    try:
        with serial.Serial(hplc_port, baudrate=9600, timeout=1) as ser:
            # Set flow rate: FIxxxxx where unit is 0.001 mL/min (e.g., 20.000 mL/min → FI20000)
            flow_cmd = f"FI{int(hplc_flow_rate_ml_min * 1000):05d}"
            send_command(ser, flow_cmd)

            # Run
            send_command(ser, "RU")
            print(f"[{comment}] HPLC running {volume_ml} mL @ {hplc_flow_rate_ml_min} mL/min "
                  f"≈ {run_time_sec:.1f} s...")
            time.sleep(run_time_sec)

            # Stop
            send_command(ser, "ST")
            print(f"[{comment}] HPLC → 20 mL done.")
    except serial.SerialException as e:
        print(f"[{comment}] HPLC Serial Error: {e}")

# Example call with method selection
control_pumps_and_measure_spectrum(
    12.5, 12.5, 12.5, 12.5, 12.5, 12.5, 12.5,
    method_index=2
)
# Dead volume wash
run_channel1_and_hplc_20ml(syringe_port='COM4', hplc_port='COM4', hplc_flow_rate_ml_min=20.0, comment='ODE')
