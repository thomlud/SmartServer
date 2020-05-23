#!/usr/bin/python3

# Python code to read values from Smart Meter via SML (smart message language)
# created: Alexander Kabza, Mar 1, 2016
# last mod: Thomas Ludwig, 2019-05-22 onto EMH ED300L
# For documentation and further information see http://www.kabza.de/MyHome/SmartMeter.html
import binascii
import flask
import json
import sys
import serial
import threading
import time


def writexml(t, W1, W2, P):
    """ writes  """
    with open('SmartMeter.xml', 'w') as file:
        file.write('<MyHomePower><SmartMeter><data name=\"timestamp\" value=\"' + t + '\"  valueunit=\"YYYY-MM-DD hh:mm:ss\" />\
                                       <data name=\"energy1\" value=\"' + str(W1) + '\" valueunit=\"Wh\" />\
                                       <data name=\"energy2\" value=\"' + str(W2) + '\" valueunit=\"Wh\" />\
                                        <data name=\"power\" value=\"' + str(P) + '\" valueunit=\"W\" /></SmartMeter></MyHomePower>')



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
    # data = data + char.encode('HEX')
    # char = codecs.encode(char_bin, "Hex")
    data = data + char.decode('ascii')
    # data = data + char
    pos = data.find(start)
    if (pos != -1):
        data = data[pos:len(data)]
    pos = data.find(end)
    if (pos != -1):
        # print(data + '\n')
        timestamp = (time.strftime("%Y-%m-%d ") + time.strftime("%H:%M:%S"))
        result = timestamp

        search = '0100010801ff'
        """ search key counter value 1 """
        pos1 = data.find(search)
        if (pos1 != -1):
            pos1 = pos1 + len(search) + 14
            value1 = data[pos1:pos1 + 10]
            energy1 = int(value1, 16) / 1e4
            print(timestamp + ' kWh: ' + search + ' = ' + value1 + ' = ' + str(energy1) + ' kWh')
            result = result + ';' + str(energy1)

        search = '0100010802ff'
        """ search key counter value 2 """
        pos2 = data.find(search)
        if (pos2 != -1):
            pos2 = pos2 + len(search) + 14
            value2 = data[pos2:pos2 + 10]
            energy2 = int(value2, 16) / 1e4
            print(timestamp + ' kWh: ' + search + ' = ' + value2 + ' = ' + str(energy2) + ' kWh')
            result = result + ';' + str(energy2)

        search = '0100100700ff'
        """ search key topical consume """
        pos3 = data.find(search)
        if (pos3 != -1):
            pos3 = pos3 + len(search) + 14
            value3 = data[pos3:pos3 + 8]
            power = int(value3, 16) / 1e1
            print('W: ' + search + ' = ' + value3 + ' = ' + str(power) + ' W')
            result = result + ';' + str(power)

        writexml(timestamp, energy1, energy2, power)

        with open('output.csv', 'a') as logfile:
            logfile.write(result + '\n')

#        file = open('message.dat', 'w')
#        file.write (data)
#        file.close()

        data = ''