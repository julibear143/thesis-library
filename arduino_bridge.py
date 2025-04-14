# arduino_bridge.py
from flask import Flask, request, jsonify
import serial
import time

app = Flask(__name__)

ARDUINO_PORT = 'COM5'  # change if needed
BAUD_RATE = 9600

@app.route('/signal_arduino', methods=['POST'])
def signal_arduino():
    try:
        with serial.Serial(ARDUINO_PORT, BAUD_RATE, timeout=1) as arduino:
            time.sleep(2)  # give Arduino time to reset
            arduino.write(b'o')  # send the signal
            print("Signal sent to Arduino to open door")
            return jsonify({'success': True})
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({'success': False, 'message': str(e)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001)
