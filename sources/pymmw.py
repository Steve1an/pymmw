#!/bin/sh
'''which' python3 > /dev/null && exec python3 "$0" "$@" || exec python "$0" "$@"
'''

#
# Copyright (c) 2018, Manfred Constapel
# This file is licensed under the terms of the MIT license.
#

#
# goto pymmw 
#

import os, sys, glob, serial, threading, json, argparse, signal, platform, time

from lib.shell import *
from lib.probe import *

# ------------------------------------------------

def _init_(data, fw):
    global mss
    if len(data) > 0 and mss is None: 
        for item in fw:            
            mss = __import__(item, fromlist=('',))
            if mss._read_(data, open(os.devnull, "w")) is None:
                return True
            mss = None
    return False


def _read_(prt, dat, timeout=2):  # observe control port and call handler when firmware is recognized

    fw = ['.'.join(os.path.splitext(item)[0].split(os.sep)) for item in glob.glob(os.sep.join(('mss', '*.py')))]
    
    cnt = 0
    ext = {}
 
    try:
        
        if len(fw) == 0:
            raise Exception('no handlers have been found')
        
        t = time.time()

        while True:
            data = prt.readline().decode('latin-1')
            if _init_(data, fw):  # firmware identified      
                break
            elif len(data) > 0:
                print(data, end='', flush=True)

            if timeout is not None:
                if time.time() - timeout > t:
                    raise Exception('no handler has been found')
            
        reset = False
        while True:
            if mss._read_(data) is not None:
                if reset:  # reset detected
                    cnt += 1
                    file = open('mss/' + os.path.splitext(mss.__file__.split(os.sep)[-1])[0] + '.cfg', 'r')
                    content = load_config(file)
                    cfg = json.loads(content)
                    cfg, par = mss._conf_(cfg)
                    mss._init_(prt, dev, cfg, dat)
                    mss._proc_(cfg, par)
                    send_config(prt, cfg, mss._read_)
                    show_config(cfg)
                reset = False
            else:
                reset = True
            data = prt.readline().decode('latin-1')
            
    except Exception as e:
        print_log(e, sys._getframe())
        sys.exit(1)
            

def _input_(prt):  # accept keyboard input and forward to control port
    while not sys.stdin.closed:
        line = sys.stdin.readline()   
        if not line.startswith('%'):
            prt.write(line.encode())

# ------------------------------------------------

if __name__ == "__main__":

    try:
        
        signal.signal(signal.SIGINT, signal.SIG_DFL)

        win = 'Windows' in platform.system()
       
        parser = argparse.ArgumentParser(description='pymmw', epilog='', add_help=True,
                                         formatter_class=argparse.ArgumentDefaultsHelpFormatter)

        parser.add_argument('-c', '--control-port', help='serial port for control communication', required=win)
        parser.add_argument('-d', '--data-port', help='serial port for data communication', required=win)
        args = parser.parse_args()
        
        dev, con, mss = None, None, None

        if not win:

            dev = usb_discover()
            if len(dev) == 0: raise Exception('no device has been detected')
    
            dev = dev[0]        
            print_log(' - '.join([dev._details_[k] for k in dev._details_]))
            
            try:
                xds_reset(dev)
                xds_test(dev)
            except Exception as e:
                print_log(e)

            prts = serial_discover(sid=dev._details_['serial'])
            if len(prts) != 2: raise Exception('unknown device configuration has been detected')
    
            if args.control_port is None: args.control_port = prts[0]
            if args.data_port is None: args.data_port = prts[1]
    
            if args.control_port != prts[0]: raise Exception('serial port {} is not available'.format(args.control_port))
            if args.data_port != prts[1]: raise Exception('serial port {} is not available'.format(args.data_port))
        
        con = serial.Serial(args.control_port, 115200, timeout=0.01)        
        if con is None: raise Exception('not able to connect to control port')

        print_log('control port: {} - data port: {}'.format(args.control_port, args.data_port))

        tusr = threading.Thread(target=_read_, args=(con, args.data_port, None if win else 2))
        tusr.start()

        tstd = threading.Thread(target=_input_, args=(con,), )
        tstd.start()

        if not win:
            xds_reset(dev)
            usb_free(dev)
        else:
            print('\nPlease carry out a reset (NRST) of the device.', file=sys.stderr, flush=True)

    except Exception as e:         
        print_log(e, sys._getframe())
        sys.exit(1)
