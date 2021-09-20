#!/usr/bin/python3

# Python code to read values from Smart Meter via SML (smart message language)
# last mod: Thomas Ludwig, 2020-05-22 onto EMH ED300L
import binascii
import random
import datetime
import flask
from flask import Flask, render_template, Response, request as freq
from flask_sqlalchemy import SQLAlchemy
import json
from math import ceil, sqrt
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import os
import platform
import queue
import requests
import serial
from threading import Thread
import time

app_port = 8000
app = Flask(__name__)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///values.db'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///power.db'
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {'connect_args': {'check_same_thread': False}}
db = SQLAlchemy(app)
sensor_delay = 5    # sensor read delay in seconds
current_power = 0
current_dt = datetime.datetime.now().strftime("%a,  %d.%m.%Y - %H:%M:%S")
log_delay_minutes = 30
screen_resolution = "low"

# # # SSE Function message announcer # # #
class MessageAnnouncer:
    """ listen() will be called by clients to receive notifications
        announce() takes messages and announces them to listeners
    """
    def __init__(self):
        self.listeners = []

    def listen(self):
        q = queue.Queue(maxsize=5)
        self.listeners.append(q)
        return q

    def announce(self, msg):
        for i in reversed(range(len(self.listeners))):
            try:
                self.listeners[i].put_nowait(msg)
            except queue.Full:
                del self.listeners[i]


announcer = MessageAnnouncer()

def format_sse(data: str, event=None) -> str:
    msg = f'data: {data}\n\n'
    if event is not None:
        msg = f'event: {event}\n{msg}'
    return msg


def convTime(ts) -> dict:
    """
    :param ts: Timestamp in int or iso-string
    :return: dict in form {"int":int , "str": str, "dt": dt}

    Convert a timestamp
    """
    if type(ts) == int:
        dt = datetime.datetime.fromtimestamp(ts)
    elif type(ts) == str:
        dt = datetime.datetime.fromisoformat(ts)
    elif type(ts) == datetime.datetime:
        dt = ts
    else:
        return None
    answer = {"int": dt.timestamp(), "str": dt.isoformat(), "dt": dt}
    return answer

class PowerLog(db.Model):
    __tablename__ = 'power_log'
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.String, nullable=False)
    energy1 = db.Column(db.Float, nullable=False)
    energy2 = db.Column(db.Float, nullable=False)
    power = db.Column(db.Float, nullable=True)

    def __init__(self, timestamp, energy1, energy2, power):
        self.timestamp = timestamp
        self.energy1 = energy1
        self.energy2 = energy2
        self.power = power
        
    def __repr__(self):
        answer = json.dumps({"id": self.id, "datetime": self.timestamp,
                             "energy1": self.energy1, "energy2": self.energy2, "power": self.power})
        return answer

class MinuteTable(db.Model):
    __tablename__ = 'minute_table'
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

class HourTable(db.Model):
    __tablename__ = 'hour_table'
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

class DayTable(db.Model):
    __tablename__ = 'day_table'
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

class MonthTable(db.Model):
    __tablename__ = 'month_table'
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


db.create_all()

class DbManager:
    def __init__(self):
        self.last_ts = datetime.datetime.now()
        self.current_power_list = []
        self.lastMinuteRow = None
        self.lastHourRow = None
        self.lastDayRow = None
        self.lastMonthRow = None
        self.update_values()

    def update_values(self):
        self.lastMinuteRow = self.get_last_db_value(MinuteTable)
        self.lastHourRow = self.get_last_db_value(HourTable)
        self.lastDayRow = self.get_last_db_value(DayTable)
        self.lastMonthRow = self.get_last_db_value(MonthTable)

    def get_last_db_value(self, table):
        answer = db.session.query(table).order_by(table.id.desc()).first()
        return answer

    def append_data(self, ts, energy1, energy2, power=0):
        newLog = PowerLog(timestamp=ts.isoformat(), energy1=energy1, energy2=energy2, power=power)
        db.session.add(newLog)
        print("Powerlog logged on %s" % ts.isoformat())
        logtime = convTime(ts)["dt"]
        try:
            if logtime - datetime.timedelta(minutes=1) >= convTime(self.lastMinuteRow.timestamp)["dt"]:
                new = MinuteTable(timestamp=convTime(ts)["str"], energy1=energy1, energy2=energy2)
                db.session.add(new)
                print("MinuteTable logged on %s" % ts.isoformat())
                if logtime - datetime.timedelta(minutes=60) >= convTime(self.lastHourRow.timestamp)["dt"]:
                    new_h = HourTable(timestamp=convTime(ts)["str"], energy1=energy1, energy2=energy2)
                    db.session.add(new_h)
                    print("HourTable logged on %s" % ts.isoformat())
                    if logtime - datetime.timedelta(day=1) >= convTime(self.lastDayRow.timestamp)["dt"]:
                        new_d = DayTable(timestamp=convTime(ts)["str"], energy1=energy1, energy2=energy2)
                        db.session.add(new_d)
                        print("DayTable logged on %s" % ts.isoformat())
                        if logtime - datetime.timedelta(month=1) >= convTime(self.lastMonthRow.timestamp)["dt"]:
                            new_m = MonthTable(timestamp=convTime(ts)["str"], energy1=energy1, energy2=energy2)
                            db.session.add(new_m)
                            print("MonthTable logged on %s" % ts.isoformat())
                db.session.commit()
                self.update_values()
        except:
            new = MinuteTable(timestamp=convTime(ts)["str"], energy1=energy1, energy2=energy2)
            db.session.add(new)
            new_h = HourTable(timestamp=convTime(ts)["str"], energy1=energy1, energy2=energy2)
            db.session.add(new_h)
            new_d = DayTable(timestamp=convTime(ts)["str"], energy1=energy1, energy2=energy2)
            db.session.add(new_d)
            new_m = MonthTable(timestamp=convTime(ts)["str"], energy1=energy1, energy2=energy2)
            db.session.add(new_m)
            db.session.commit()
            self.update_values()

    def append_current_power(self, ts, power):
        if ts - datetime.timedelta(minutes=1) > self.last_ts:
            if len(self.current_power_list) > 60:
                self.current_power_list.pop(0)
            h = ts.strftime("%H:%M")
            self.current_power_list.append({"time": h, "power": power})
            self.last_ts = ts

    def get_curr_power_list(self):
        return self.current_power_list


dbm = DbManager()

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
        dt = datetime.datetime.today()
        rand = random.random()
        power = ceil(rand*1000)
        current_power = power
        current_dt = datetime.datetime.now().strftime("%a,  %d.%m.%Y - %H:%M:%S")
        energy1 = q["energy1"] + power/1000
        energy2 = q["energy2"] + power/1000
        msg = format_sse(data=str(current_power))
        # msg = format_sse(data="reload")
        announcer.announce(msg=format_sse(data="reload"))
        print(msg)

        dbm.append_current_power(ts=dt, power=power)
        dbm.append_data(dt, energy1, energy2, power)
        # dh.append_log(ts=dt, energy1=energy1, energy2=energy2, delay=log_delay_minutes)
        time.sleep(delay)

def _powermeter(sens_delay):
    global current_power
    global current_dt
    power = 0
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
            dt = datetime.datetime.today()
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
            current_dt = datetime.datetime.now().strftime("%a,  %d.%m.%Y - %H:%M:%S")
            # msg = format_sse(data=str(current_power))
            # msg = format_sse(data="reload")
            # announcer.announce(msg=format_sse(data="reload"))
            # print(msg)
            # dbm.append_current_power(ts=dt, power=power)
            # dbm.append_data(dt, energy1, energy2, power)
            time.sleep(sens_delay)
            
def powermeter(sens_delay):
    global current_power
    global current_dt
    power = 0
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
            dt = datetime.datetime.now()
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
            current_dt = datetime.datetime.now().strftime("%a,  %d.%m.%Y - %H:%M:%S")
            jdata = json.dumps({"timestamp": dt.isoformat(timespec="seconds"), "energyNT": energy1, "energyHT": energy2, "power":power})
            r = requests.post("http://localhost:%s/input" % str(app_port), jdata,
                          headers={'Content-type': 'application/json'}, timeout=2.000)
            print(r)
            '''if db_write_level == 1:
                if power:
                    dbm.append_current_power(ts=dt, power=power)
                if energy1 and energy2:
                    dbm.append_data(ts=dt, energy1=energy1, energy2=energy2, power=power)'''
            data = ''
            time.sleep(sens_delay)
            
            

def queryData():
    vals = db.session.query(PowerLog).order_by(PowerLog.id.desc()).first()
    return str(vals)

'''def _listData_timefilter(filt):
    valrange = db.session.query(PowerLog).filter(PowerLog.timestamp >= filt).all()
    print(str(valrange))
    return valrange

def list_timediff(ts, sec):
    diff = datetime.datetime.now() - datetime.timedelta(seconds=sec)
    # diff = datetime(2020, 6, 22, 10, 53, 0)
    result = _listData_timefilter(diff)
    return str(result)
'''

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

'''def get_last_72_values() -> list:
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
'''

def _parse_list(val_list) -> list:
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

# values72 = parse_list(get_last_72_values())
# plot_hourly_graph(values72)

@app.route('/listen', methods=['GET'])
def listen():
    def stream():
        messages = announcer.listen()  # returns a queue.Queue
        while True:
            msg = messages.get()  # blocks until a new message arrives
            yield msg
    return Response(stream(), mimetype='text/event-stream')


@app.route('/input', methods=['GET', 'POST'])
def inputdata():
    answer = "Failed"
    content = freq.get_json(silent=True, cache=False)
    if content:
        print(content)
        dt = datetime.datetime.fromisoformat(content["timestamp"])
        if content["power"]:
            dbm.append_current_power(ts=dt, power=content["power"])
            # msg = format_sse(data=str(current_power))
            # msg = format_sse(data="reload")
            announcer.announce(msg=format_sse(data="reload"))
        if content["energyNT"] and content["energyHT"]:
            dbm.append_data(ts=dt, energy1=content["energyNT"], energy2=content["energyHT"], power=content["power"])
            answer = "Success"           
    return answer
                               

@app.route('/test', methods=['GET', 'POST'])
def test():
    content = flask.request.values
    if content:
        print("##### Got content items: #####")
        for k, v in content.items():
            print('Key = {} and Value = {}'.format(k, v))

    files = flask.request.files
    if files:
        print("##### Got files: #####")
        for k, v in files.items():
            print('Key = {} and Value = {}'.format(k, v))

    maybe_json = flask.request.get_json(silent=True, cache=False)
    if maybe_json:
        print("##### Got json: #####")
        thejson = json.dumps(maybe_json, ensure_ascii=False, indent=4)
        print('thejson = ' + thejson)
    else:
        thejson = "no json"
        print('thejson = ' + thejson)

    args = flask.request.args  # args is ?user=john
    if args:
        print("##### Got args: #####")
        for k, v in args.items():
            print('Args with Key = {} and Value = {}'.format(k, v))

    form = flask.request.form    # key/value sets
    if form:
        print("##### Got form data: #####")
        for k, v in form.items():
            print('Form with Key = {} and Value = {}'.format(k, v))

    print("##### Data as text content: #####")
    print(flask.request.get_data(as_text=True))
    print("mimetype = %s" % flask.request.mimetype)
    print("%s" % flask.request.content_length)
    print("from Server: %s" % flask.request.host)
    answer = "200"
    
    return answer


@app.route('/', methods=['GET', 'POST'])
def home():
    content = freq.values
    if content:
        for item in content.items():
            print(item)
    currentvalues = json.loads(queryData())
    ts = datetime.datetime.now()
    power_line = set_multiline(dbm.get_curr_power_list())
    print(power_line)
    if current_power <= 500:
        currentlevel = "low"
    elif current_power <= 2000:
        currentlevel = "middle"
    else:
        currentlevel = "high"

    return render_template('home.html', currentvalues=currentvalues, currentlevel=currentlevel,
                           current_power=current_power, current_dt=current_dt,
                           power_line=power_line, cpl=dbm.get_curr_power_list())

@app.route('/current')
def current_use():
    return json.dumps(dbm.get_curr_power_list())

@app.route('/get/<command>')
def getDbValue(command):
    resultList = []
    if command == "minute":
        valList = db.session.query(MinuteTable).order_by(MinuteTable.id.desc()).all()
    elif command == "hour":
        valList = db.session.query(HourTable).order_by(HourTable.id.desc()).all()
    elif command == "day":
        valList = db.session.query(DayTable).order_by(DayTable.id.desc()).all()
    elif command == "month":
        valList = db.session.query(MonthTable).order_by(MonthTable.id.desc()).all()

    if valList:
        lastVal = {}
        max = 60 if len(valList) >= 60 else len(valList)
        for i in range(max):
            ts = valList[i].timestamp
            energyNT = round(valList[i].energy1, 3)
            energyHT = round(valList[i].energy2, 3)
            currentVal = {"ts": ts, "Strom_NT": energyNT, "Strom_HT": energyHT}
            if lastVal:
                currentVal["used_NT"] = round(lastVal["Strom_NT"] - currentVal["Strom_NT"], 3)
                currentVal["used_HT"] = round(lastVal["Strom_HT"] - currentVal["Strom_HT"], 3)
            resultList.append(currentVal)
            lastVal = currentVal

    if resultList:
        return json.dumps(resultList, indent=2)
    else:
        return "{}"


@app.route('/api/<command>')
def api(command):
    if command == "listdb":
        answer = db.session.query(PowerLog).all()
        return answer
    elif command == "val1h":
        ts = datetime.now()
        answer = list_timediff(ts, 60)
        return answer


def run_app():

    if platform.system() == "Linux" and 'ttyUSB0' in os.listdir('/dev'):
        ''' dirname = os.environ['/dev']
            objects = os.listdir(dirname)'''
        t1 = Thread(target=powermeter, args=[sensor_delay,])
        t1.start()
    else:
        t1 = Thread(target=pm_simulator, args=[sensor_delay,])
        t1.start()
    app.run(host='0.0.0.0', port=app_port, debug=True, use_reloader=True, threaded=True)


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