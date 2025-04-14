from flask import Flask, render_template, request
import serial
import time
import os

# Initialize Flask app and specify template folder
app = Flask(__name__, template_folder=os.path.join('web_portal', 'templates'))

# Configuration
COM_PORT = os.getenv('COM_PORT', 'COM5')  # Use environment variable or default to 'COM3'
BAUD_RATE = 9600

@app.route('/')
def index():
    return render_template('ko.html')  # Flask should now look inside 'web_portal/templates/'

@app.route('/trigger-return', methods=['POST'])
def trigger_return():
    try:
        with serial.Serial(COM_PORT, BAUD_RATE, timeout=1) as arduino:
            time.sleep(2)  # Allow time for the connection to establish
            arduino.write(b'o')  # Send 'o' to Arduino to trigger door (from Confirm Return)
        return render_template('ko.html', status="Return initiated. Please insert the book.")
    except serial.SerialException as e:
        if "PermissionError" in str(e):
            return render_template('ko.html', status="Error: Access denied. Ensure the port is not in use by another application.")
        return render_template('ko.html', status=f"Serial error: {e}")
    except Exception as e:
        return render_template('ko.html', status=f"Error: {e}")
if __name__ == '__main__':
    app.run(debug=True)