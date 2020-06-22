#!/usr/bin/python3

# Python code to read values from Smart Meter via SML (smart message language)
# last mod: Thomas Ludwig, 2020-05-22 onto EMH ED300L
import binascii
from datetime import datetime
from flask import Flask, render_template
from flask_sqlalchemy import SQLAlchemy
import json
import platform
import pprint
# import sys
import serial
from threading import Thread
import time


app = Flask(__name__)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///values.db'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///power.db'
db = SQLAlchemy(app)

class PowerLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    datetime = db.Column(db.DateTime, nullable=False)
    timestamp = db.Column(db.String, nullable=True)
    energy1 = db.Column(db.Float, nullable=False)
    energy2 = db.Column(db.Float, nullable=False)
    power = db.Column(db.Float, nullable=False)
    
    def __init__(self, timestamp, energy1, energy2, power):
        self.timestamp = timestamp
        self.datetime = datetime.today()
        self.energy1 = energy1
        self.energy2 = energy2
        self.power = power
        
    def __repr__(self):
        answer = json.dumps({"id": self.id, "datetime": datetime, "timestamp": self.timestamp,
                             "energy1": self.energy1, "energy2": self.energy2,
                             "power": self.power}, indent=4)
        return answer

db.create_all()


def writexml(t, W1, W2, P):
    """ writes  """
    with open('SmartMeter.xml', 'w') as file:
        file.write('<MyHomePower><SmartMeter>\
                    <data name=\"timestamp\" value=\"' + t + '\"  valueunit=\"YYYY-MM-DD hh:mm:ss\" />\
                    <data name=\"energy1\" value=\"' + str(W1) + '\" valueunit=\"Wh\" />\
                    <data name=\"energy2\" value=\"' + str(W2) + '\" valueunit=\"Wh\" />\
                    <data name=\"power\" value=\"' + str(P) + '\" valueunit=\"W\" /></SmartMeter></MyHomePower>')


def powermeter():
    port = serial.Serial(
        port='/dev/ttyUSB0',
        baudrate=9600,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        bytesize=serial.EIGHTBITS
    )
    # port.open();
    start = '1b1b1b1b01010101'
    end = '1b1b1b1b1a'
    data = ''
    while True:
        char_bin = port.read()
        char = binascii.hexlify(char_bin)
        data = data + char.decode('ascii')
        pos = data.find(start)
        if pos != -1:
            data = data[pos:len(data)]
        pos = data.find(end)
        if pos != -1:
            timestamp = (time.strftime("%Y-%m-%d ") + time.strftime("%H:%M:%S"))
            dt = datetime.utcnow
            result = timestamp
            search = '0100010801ff'
            """ search key counter value 1 """
            pos1 = data.find(search)
            if pos1 != -1:
                pos1 = pos1 + len(search) + 14
                value1 = data[pos1:pos1 + 10]
                energy1 = int(value1, 16) / 1e4
                print(timestamp + ' kWh: ' + search + ' = ' + value1 + ' = ' + str(energy1) + ' kWh')
                result = result + ';' + str(energy1)
            search = '0100010802ff'
            """ search key counter value 2 """
            pos2 = data.find(search)
            if pos2 != -1:
                pos2 = pos2 + len(search) + 14
                value2 = data[pos2:pos2 + 10]
                energy2 = int(value2, 16) / 1e4
                print(timestamp + ' kWh: ' + search + ' = ' + value2 + ' = ' + str(energy2) + ' kWh')
                result = result + ';' + str(energy2)
            search = '0100100700ff'
            """ search key topical consume """
            pos3 = data.find(search)
            if pos3 != -1:
                pos3 = pos3 + len(search) + 14
                value3 = data[pos3:pos3 + 8]
                power = int(value3, 16) / 1e1
                print('W: ' + search + ' = ' + value3 + ' = ' + str(power) + ' W')
                result = result + ';' + str(power)
            # writexml(timestamp, energy1, energy2, power)
            pl = PowerLog(timestamp=timestamp, energy1=energy1, energy2=energy2, power=power)
            db.session.add(pl)
            db.session.commit()
            # with open('output.csv', 'a') as logfile:
            #    logfile.write(result + '\n')
            data = ''
            time.sleep(5)

def queryData():
    vals = db.session.query(PowerLog).order_by(PowerLog.id.desc()).first()
    return str(vals)

def listData():
    pass
    filter = ""
    valrange = db.session.query(PowerLog).filter_by(timestamp=filter).order_by(PowerLog.id.desc()).all


@app.route('/')
def home():
    currentvalues = json.loads(queryData())
    if currentvalues['power'] <= 500:
        currentlevel = "low"
    elif currentvalues['power'] <= 2000:
        currentlevel = "middle"
    else:
        currentlevel = "high"

    return render_template('home.html', currentvalues=currentvalues, currentlevel=currentlevel)


def main():
    if platform.system() == "Linux":
       # powermeter()
       t1 = Thread(target=powermeter)
       t1.start()
    app.run(host='0.0.0.0', port=80, debug=True, use_reloader=True)


if __name__ == "__main__":
    main()