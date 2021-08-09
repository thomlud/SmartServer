#!/usr/bin/python3

# Python code to read values from Smart Meter via SML (smart message language)
# last mod: Thomas Ludwig, 2020-05-22 onto EMH ED300L
import binascii
import random
from datetime import *
from flask import Flask, render_template, request as freq
from flask_sqlalchemy import SQLAlchemy
import json
from math import ceil, sqrt
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import os
import platform
import serial
from threading import Thread
import time


app = Flask(__name__)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///values.db'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///power.db'
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {'connect_args': {'check_same_thread': False}}
db = SQLAlchemy(app)
sensor_delay = 5    # sensor read delay in seconds
current_power = 0
current_dt = datetime.now().strftime("%a,  %d.%m.%Y - %H:%M:%S")
log_delay_minutes = 30
screen_resolution = "low"

class PowerLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.String, nullable=False)
    energy1 = db.Column(db.Float, nullable=False)
    energy2 = db.Column(db.Float, nullable=False)

    def __init__(self, timestamp, energy1, energy2):
        self.timestamp = timestamp
        self.energy1 = energy1
        self.energy2 = energy2
        
    def __repr__(self):
        answer = json.dumps({"id": self.id, "datetime": self.timestamp,
                             "energy1": self.energy1, "energy2": self.energy2})
        return answer

class MinuteTable(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    datetime = db.Column(db.DateTime, nullable=False)
    energy1 = db.Column(db.Float, nullable=False)
    energy2 = db.Column(db.Float, nullable=False)

    def __init__(self, datetime, energy1, energy2):
        self.datetime = datetime
        self.energy1 = energy1
        self.energy2 = energy2

    def __repr__(self):
        answer = json.dumps({"id": self.id, "datetime": self.datetime.strftime("%Y-%m-%d %H:%M:%S"),
                             "energy1": self.energy1, "energy2": self.energy2})
        return answer

db.create_all()


class DataHandler:
    def __init__(self):
        self.current_power_list = []
        self.last_cpl_timestamp = datetime(2000, 1, 1, 0, 0, 0)
        if self.query_last_log():
            self.last_db_timestamp = datetime.fromisoformat(self.query_last_log().timestamp)
        else:
            self.last_db_timestamp = datetime(2000, 1, 1, 0, 0, 0)

    def append_current_power(self, ts, power):
        if ts - timedelta(minutes=1) > self.last_cpl_timestamp:
            if len(self.current_power_list) > 60:
                self.current_power_list.pop(0)
            h = ts.strftime("%H:%M")
            self.current_power_list.append({"time": h, "power": power})
            self.last_cpl_timestamp = ts

    def get_curr_power_list(self):
        return self.current_power_list

    def query_last_log(self):
        vals = db.session.query(PowerLog).order_by(PowerLog.id.desc()).first()
        return vals

    def query_loglist(self):
        vals = db.session.query(PowerLog).order_by(PowerLog.id.desc()).all()
        return vals

    def append_log(self, ts, energy1, energy2, delay=29):
        if ts - timedelta(minutes=delay) > self.last_db_timestamp:
            pl = PowerLog(timestamp=ts.isoformat(), energy1=energy1, energy2=energy2)
            db.session.add(pl)
            db.session.commit()
            print("db logged on %s" % ts.isoformat())
            self.last_db_timestamp = ts

dh = DataHandler()

def writexml(t, W1, W2, P):
    """ writes  """
    with open('SmartMeter.xml', 'w') as file:
        file.write('<MyHomePower><SmartMeter>\
                    <data name=\"timestamp\" value=\"' + t + '\"  valueunit=\"YYYY-MM-DD hh:mm:ss\" />\
                    <data name=\"energy1\" value=\"' + str(W1) + '\" valueunit=\"Wh\" />\
                    <data name=\"energy2\" value=\"' + str(W2) + '\" valueunit=\"Wh\" />\
                    <data name=\"power\" value=\"' + str(P) + '\" valueunit=\"W\" /></SmartMeter></MyHomePower>')

def pm_simulator(sens_delay):
    global current_power
    global current_dt
    delay = sens_delay * 2
    while True:
        v = queryData()
        if not v == 'None':
            q = json.loads(v)
        else:
            q = {"energy1": 1110, "energy2": 2220}
        dt = datetime.today()
        rand = random.random()
        power = ceil(rand*1000)
        current_power = power
        current_dt = datetime.now().strftime("%a,  %d.%m.%Y - %H:%M:%S")
        energy1 = q["energy1"] + power/1000
        energy2 = q["energy2"] + power/1000
        dh.append_current_power(ts=dt, power=power)
        dh.append_log(ts=dt, energy1=energy1, energy2=energy2, delay=log_delay_minutes)
        time.sleep(delay)

def powermeter(sens_delay):
    global current_power
    global current_dt
    db_write_level = 1
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
        ''' if db_write_level == 1:
            db_write_level = 0
        else:'''
        db_write_level = 1

        char_bin = port.read()
        char = binascii.hexlify(char_bin)
        data = data + char.decode('ascii')
        pos = data.find(start)
        if pos != -1:
            data = data[pos:len(data)]
        pos = data.find(end)
        if pos != -1:
            timestamp = (time.strftime("%Y-%m-%d ") + time.strftime("%H:%M:%S"))
            dt = datetime.today()
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
            current_power = power
            current_dt = datetime.now().strftime("%a,  %d.%m.%Y - %H:%M:%S")
            if db_write_level == 1:
                if power:
                    dh.append_current_power(ts=dt, power=power)
                if energy1 and energy2:
                    dh.append_log(ts=dt, energy1=energy1, energy2=energy2, delay=log_delay_minutes)
            data = ''
            time.sleep(sens_delay)

def queryData():
    vals = db.session.query(PowerLog).order_by(PowerLog.id.desc()).first()
    return str(vals)

def _listData_timefilter(filt):
    valrange = db.session.query(PowerLog).filter(PowerLog.timestamp >= filt).all()
    print(str(valrange))
    return valrange

def list_timediff(ts, sec):
    diff = datetime.now() - timedelta(seconds=sec)
    # diff = datetime(2020, 6, 22, 10, 53, 0)
    result = _listData_timefilter(diff)
    return str(result)

def set_multiline(vals: list) -> str:
    height = 300
    length = 800
    if len(vals) > 0:
        num = length / len(vals)
        step = int(num)
    else:
        step = 1
    counter = 0
    valstr = ""
    for i in range(len(vals)):
        power = height - int(sqrt(vals[i]["power"])*2)
        valstr += "{},{} ".format(counter, power)
        counter += step
    return valstr

def get_last_72_values() -> list:
    """ returns a list of the latest 72 lines
        from db in form [datetime, nt, ht] """
    val_list = []
    lines = dh.query_loglist()
    last = len(lines)
    for line in lines:
        if line.id >= last - 71:
            dt = datetime.fromisoformat(line.timestamp)
            nt = line.energy1
            ht = line.energy2
            val_list.append([dt, nt, ht])
    return val_list

def parse_list(val_list) -> list:
    """ parses the list of power values into consumption
        returns a list of 3 lists: datetime | used_nt | used_ht
    """
    timeList = []
    ntList = []
    htList = []
    last_nt = 0
    last_ht = 0
    while val_list:
        row = val_list.pop()
        t, nt_val, ht_val = row
        if not last_nt == 0 and not last_ht == 0:
            used_nt = (nt_val - last_nt) * 1000
            used_ht = (ht_val - last_ht) * 1000
            timeList.append(t)
            ntList.append(int(used_nt))
            htList.append(int(used_ht))
        last_nt = nt_val
        last_ht = ht_val
    usage_list = [timeList, ntList, htList]
    return usage_list

def plot_hourly_graph(value_list):
    # vl = value_list
    # vl = np.array(value_list)
    vl = [np.array(value_list[0]), np.array(value_list[1]), np.array(value_list[2])]
    fig, ax = plt.subplots()
    ax.plot(vl[0], vl[1], 'r', vl[0], vl[2])  # plot-line
    datemin = np.datetime64(vl[0][0], 'h')
    datemax = np.datetime64(vl[0][-1], 'h') + np.timedelta64(1, 'h')
    ax.set_xlim(datemin, datemax)

    ax.xaxis.set_major_locator(mdates.HourLocator(interval=4))  # set x descriptions
    ax.xaxis.set_minor_locator(mdates.HourLocator())    # set x separators
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M')) # set description format


    ax.grid(True)   # set grid
    fig.autofmt_xdate() # rotates x axis descriptors
    plt.title('last 36h')
    plt.ylabel('Verbrauch')
    plt.savefig('hourly_graph.png')
    # plt.show()

values72 = parse_list(get_last_72_values())
plot_hourly_graph(values72)

@app.route('/', methods=['GET', 'POST'])
def home():
    content = freq.values
    if content:
        for item in content.items():
            print(item)
    currentvalues = json.loads(queryData())
    ts = datetime.now()
    # values_1m = json.loads(list_timediff(ts, 60))
    # values_15m = json.loads(list_timediff(ts, 900))
    power_line = set_multiline(dh.get_curr_power_list())
    # quarter_line = set_multiline(values_15m)
    print(power_line)
    if current_power <= 500:
        currentlevel = "low"
    elif current_power <= 2000:
        currentlevel = "middle"
    else:
        currentlevel = "high"

    return render_template('home.html', currentvalues=currentvalues, currentlevel=currentlevel,
                           current_power=current_power, current_dt=current_dt, power_line=power_line, cpl=dh.get_curr_power_list())

@app.route('/current')
def current_use():
    return json.dumps(dh.get_curr_power_list())

@app.route('/test/<command>')
def test(command):
    if command == "listdb":
        answer = db.session.query(PowerLog).all()
        return answer
    elif command == "val1h":
        ts = datetime.now()
        answer = list_timediff(ts, 60)
        return answer



def run_app():

    if platform.system() == "Linux" and 'ttyUSB0' in os.listdir(os.environ('/dev')):
        ''' dirname = os.environ['/dev']
            objects = os.listdir(dirname)'''
        t1 = Thread(target=powermeter, args=[sensor_delay,])
        t1.start()
    else:
        t1 = Thread(target=pm_simulator, args=[sensor_delay,])
        t1.start()
    app.run(host='0.0.0.0', port=8000, debug=True, use_reloader=True)


if __name__ == "__main__":
    run_app()

"""import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.cbook as cbook

# Load a numpy structured array from yahoo csv data with fields date, open,
# close, volume, adj_close from the mpl-data/example directory.  This array
# stores the date as an np.datetime64 with a day unit ('D') in the 'date'
# column.
data = cbook.get_sample_data('goog.npz', np_load=True)['price_data']

fig, ax = plt.subplots()
ax.plot('date', 'adj_close', data=data)

# Major ticks every 6 months.
fmt_half_year = mdates.MonthLocator(interval=6)
ax.xaxis.set_major_locator(fmt_half_year)

# Minor ticks every month.
fmt_month = mdates.MonthLocator()
ax.xaxis.set_minor_locator(fmt_month)

# Text in the x axis will be displayed in 'YYYY-mm' format.
ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))


# Format the coords message box, i.e. the numbers displayed as the cursor moves
# across the axes within the interactive GUI.
ax.format_xdata = mdates.DateFormatter('%Y-%m')
ax.format_ydata = lambda x: f'${x:.2f}'  # Format the price.
ax.grid(True)

# Rotates and right aligns the x labels, and moves the bottom of the
# axes up to make room for them.
fig.autofmt_xdate()

plt.show()
"""