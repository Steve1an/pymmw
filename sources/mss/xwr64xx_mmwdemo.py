#
# Copyright (c) 2018, Manfred Constapel
# This file is licensed under the terms of the MIT license.
#

#
# TI IWR1443 ES2.0 EVM @ mmWave SDK demo of SDK 1.2.0.5
#

import sys, json, serial, threading

from lib.shell import *
from lib.helper import *
from lib.utility import *

# ------------------------------------------------

_meta_ = {
    'dev': 'xWR64xx',
    'mss': 'MMW Demo',
    'ver': ('01.02.00.05', '03.04.00.02'),
    'cli': 'mmwDemo:/>',
    'seq': b'\x02\x01\x04\x03\x06\x05\x08\x07',
    'blk': 32,
    'aux': 921600,
    'ant': (4, 3),
    
    # define apps to run
    'app': {
      '''  'rangeProfile':        ('plot_range_profile', 'capture_range_profile'),
        'noiseProfile':        ('plot_range_profile', ), 
        'detectedObjects':     ('plot_detected_objects', 'simple_cfar_clustering'),'''
        'rangeAzimuthHeatMap': ('plot_range_azimuth_heat_map', )
       # 'rangeDopplerHeatMap': ('plot_range_doppler_heat_map', )
    }
}

# ------------------------------------------------

apps = {}
verbose = True

# ------------------------------------------------

def _read_(dat, target=sys.stdout):
    target.write(dat)
    target.flush()
    for ver in _meta_['ver']:
        if all((tag in dat for tag in (_meta_['dev'], _meta_['mss'], ver))): return None  # reset detected
    if _meta_['cli'] in dat: return True  # cli ready
    return False  # unknown


def _init_(prt, dev, cfg, dat):
    aux = serial.Serial(dat, _meta_['aux'], timeout=0.01)
    taux = threading.Thread(target=_data_, args=(aux,))
    taux.start()
        

def _conf_(cfg):
    
    global verbose
    
    key = _meta_['dev']        

    c = dict(cfg)
    p = {'loglin': float('nan'), 'fftcomp': float('nan'), 'rangebias': float('nan')}
    
    if '_comment_' in c:
        c.pop('_comment_', None)  # remove entry        
    
    if '_settings_' in c:
        
        rx_ant = int(c['_settings_']['rxAntennas'])
        tx_ant = int(c['_settings_']['txAntennas'])
        
        # common
        if c['channelCfg']['rxMask'] is None:
            c['channelCfg']['rxMask'] = 2**rx_ant - 1

        if c['channelCfg']['txMask'] is None:
            n = tx_ant
            if n == 1: n = 0
            else: n = 2 * n
            c['channelCfg']['txMask'] = 1 + n

        if c['channelCfg']['cascading'] is None:
            c['channelCfg']['cascading'] = 0  # always 0

        # range bias for post-processing
        if 'rangeBias' not in c['_settings_'] or c['_settings_']['rangeBias'] is None:
            c['_settings_']['rangeBias'] = 0
        
        # range bias for pre-processing
        if 'compRangeBiasAndRxChanPhase' in c:
            
            if c['compRangeBiasAndRxChanPhase']['rangeBias'] is None:
                c['compRangeBiasAndRxChanPhase']['rangeBias'] = c['_settings_']['rangeBias']
            
            if c['compRangeBiasAndRxChanPhase']['phaseBias'] is None or \
                type(c['compRangeBiasAndRxChanPhase']['phaseBias']) == list and \
                 len(c['compRangeBiasAndRxChanPhase']['phaseBias']) == 0:
                 c['compRangeBiasAndRxChanPhase']['phaseBias'] = [1, 0] * _meta_['ant'][0] * _meta_['ant'][1]

        # cli output
        if 'verbose' in c['_settings_'] and c['_settings_']['verbose'] is not None:
            verbose = c['_settings_']['verbose']
        
        # xWR64xx and xWR68xx related
        if key == 'xWR64xx' or key == 'xWR68xx':

            if key == 'xWR64xx':
                
                if c['dfeDataOutputMode']['type'] is None:
                    c['dfeDataOutputMode']['type'] = 1  # legacy (no subframes)

                if c['adcCfg']['adcBits'] is None:
                    c['adcCfg']['adcBits'] = 2  # 16 bit

            log_lin_scale = 1.0 / 512
            if num_tx_elev_antenna(c) == 1: log_lin_scale = log_lin_scale * 4.0 / 3  # MMWSDK-439

            fft_scale_comp_1d = fft_doppler_scale_compensation(32, num_range_bin(c))
            fft_scale_comp_2d = 1;                
            fft_scale_comp = fft_scale_comp_2d * fft_scale_comp_1d                

        # xWR16xx or xWR18xx related
        else:

            if c['dfeDataOutputMode']['type'] == 3:
                raise NotImplementedError('xWR16xx|xWR18xx: subframes')
        
        p['log_lin'], p['fft_comp'], p['range_bias'] = log_lin_scale, fft_scale_comp, c['_settings_']['rangeBias']        
        
        c.pop('_settings_', None)  # remove entry
                
    return c, p


def _proc_(cfg, par, err={1: 'miss', 2: 'exec', 3: 'plot'}):
    global apps
    for _, app in apps.items(): app.kill()
    apps.clear()
    for cmd, app in _meta_['app'].items():
        if type(app) not in (list, tuple): app = (app,)             
        for item in app:
            if cmd in cfg['guiMonitor'] and cfg['guiMonitor'][cmd] == 1 and item is not None:
                if item not in apps:
                    apps[item], values = exec_app(item, (cfg, par, ))
                    if values is None: values = []
                    code = apps[item].poll()
                    if code is None:
                        print_log(item, values)
                        tapp = threading.Thread(target=_grab_, args=(item,))
                        tapp.start()
                    else:
                        print_log(item, values, RuntimeError(err[code]))


def _pipe_(dat):
    for tag in apps:
        if apps[tag] is None: continue
        try:
            apps[tag].stdin.write(str.encode(dat + '\n'))
            apps[tag].stdin.flush()
        except Exception as e:
            print_log(e, sys._getframe(), tag)
            apps[tag].kill()
            apps[tag] = None


def _grab_(tag):
    try:
        while True:
            line = apps[tag].stderr.readline()
            if line:
                line = line.decode('latin-1')
                print_log(None, tag, line.strip())
    except:
        pass    

# ------------------------------------------------

def _data_(prt):  # observe auxiliary port and process incoming data
    
    if not prt.timeout:
        raise TypeError('no timeout for serial port provided')

    input, output, sync, size = {'buffer': b''}, {}, False, _meta_['blk']

    while True:
        try:
            
            data = prt.read(size)
            input['buffer'] += data
            
            if data[:len(_meta_['seq'])] == _meta_['seq']:  # check for magic sequence
                
                if len(output) > 0:
                    plain = json.dumps(output)
                    _pipe_(plain)
                    if verbose:
                        print(plain, file=sys.stdout, flush=True)  # just print output to stdout
                 
                input['buffer'] = data
                input['segments'] = -1
                input['address'] = 0
                input['pages'] = 0
                input['other'] = {}
 
                output = {}                
 
                sync = True  # very first frame in the stream was seen
                
            if sync:
                flen = 0
                while flen < len(input['buffer']):  # keep things finite
                    flen = len(input['buffer'])
                    aux_buffer(input, output)  # do processing of captured bytes

        except Exception as e:
            print_log(e, sys._getframe())
            sys.exit(1)

# ------------------------------------------------

def aux_buffer(input, output):

    def aux_head(dat):  # read first few bytes (aka header) of any frame
        n = 36
        m =        dat[ 0: 8]
        v = intify(dat[ 8:12], 10)
        l = intify(dat[12:16])
        d = intify(dat[16:20], 10)
        f = intify(dat[20:24])
        t = intify(dat[24:28])
        o = intify(dat[28:32])
        s = intify(dat[32:36])
        return n, v, l, d, f, t, o, s
    
    
    def aux_struct(dat):  # read any segment header
        n = 8
        t = intify(dat[ 0: 4])
        l = intify(dat[ 4: 8])
        return n, t, l
    
    
    def aux_descriptor(dat):  # read descriptor for detected points/objects
        n = 4
        o = intify(dat[ 0: 2])
        q = intify(dat[ 2: 4])
        return n, o, q
    
    
    def aux_object(dat, oth):  # read detected points/objects 
        
        n = 12
        
        ri = intify(dat[ 0: 2])  # range index
    
        di = intify(dat[ 2: 4])  # Doppler index
        if di > 32767: di = di - 65536
        di = -di  # circular shifted fft bins
    
        p = intify(dat[ 4: 6])  # Doppler peak value
    
        x = intify(dat[ 6: 8])
        y = intify(dat[ 8:10])
        z = intify(dat[10:12])
        
        if x > 32767: x = x - 65536
        if y > 32767: y = y - 65536
        if z > 32767: z = z - 65536
    
        qfrac = 0
        if 'qfrac' in oth: qfrac = oth['qfrac']  # q-notation is used here
        x = q_to_dec(x, qfrac)
        y = q_to_dec(y, qfrac)
        z = q_to_dec(z, qfrac)
    
        return n, ri, di, p, x, y, z
    
    
    def aux_profile(dat):  # read value from range and noise profile respectively
        n = 2
        v = intify(dat[ 0: 2])
        return n, v
    
    
    def aux_heatmap(dat, sgn, bins=1):  # read value(s) for heatmap
        v = [None,] * bins
        n = 0
        while n < bins:
            v[n] = intify(dat[ n*2: (n+1)*2])
            if sgn and v[n] > 32767: v[n] = v[n] - 65536
            n += 1
        return 2*n, v
    
    
    def aux_info(dat):  # read performance measures and statistical data
        n = 24
        ifpt = intify(dat[ 0: 4])
        tot  = intify(dat[ 4: 8])
        ifpm = intify(dat[ 8:12])
        icpm = intify(dat[12:16])
        afpl = intify(dat[16:20])
        ifpl = intify(dat[20:24])
        return n, ifpt, tot, ifpm, icpm, afpl, ifpl


    buffer, segments, address, pages, other = \
        input['buffer'], input['segments'], input['address'], \
        input['pages'], input['other']

    if len(buffer) >= 24 and address == 6:  # statistics
        n, ifpt, tot, ifpm, icpm, afpl, ifpl = aux_info(buffer)
        buffer = buffer[24:]
        address = 0
        output['device'] = {
                'time': {
                    'interframe_processing': ifpt,
                    'transmit_output': tot},
                    'processing_margin': {
                        'interframe': ifpm,
                        'interchirp': icpm},
                    'cpu_load': {
                        'active_frame': afpl,
                        'interframe': ifpl}}
    
    # entire, 2D, log mag range/Doppler array
    while len(buffer) >= 2 and address == 5 and pages > 0:  # range-doppler heatmap
        n, v = aux_heatmap(buffer, False)
        pages -= 1
        buffer = buffer[2:]
        if pages == 0: address = 0
        output['doppler'] += v

    # azimuth data from the radar cube matrix
    while len(buffer) >= 2 and address == 4 and pages > 0:  # range-azimuth heatmap
        n, v = aux_heatmap(buffer, True)
        pages -= 1
        buffer = buffer[2:]
        if pages == 0: address = 0
        output['azimuth'] += v
            
    # 1D array of data considered “noise”
    while len(buffer) >= 2 and address == 3 and pages > 0:
        n, v = aux_profile(buffer)
        pages -= 1
        buffer = buffer[2:]
        if pages == 0: address = 0
        output['noise'].append(q_to_db(v))

    # 1D array of log mag range ffts – i.e. the first column of the log mag range-Doppler matrix
    while len(buffer) >= 2 and address == 2 and pages > 0:
        n, v = aux_profile(buffer)
        pages -= 1
        buffer = buffer[2:]
        if pages == 0: address = 0
        output['range'].append(q_to_db(v))

    # object detection
    while len(buffer) >= 12 and address == 1 and pages > 0:
        n, r, d, p, x, y, z = aux_object(buffer, other)
        pages -= 1
        buffer = buffer[12:]
        if pages == 0: address = 0
        output['objects'].append({'index': (r, d), 'doppler': p, 'x': x, 'y': y, 'z': z})     

    # object detection descriptor
    if len(buffer) >= 4 and address == 1 and pages == 0:
        n, o, q = aux_descriptor(buffer)
        pages = o
        buffer = buffer[4:]
        other['qfrac'] = q

    # segment details
    if len(buffer) >= 8 and segments > 0 and address == 0 and pages == 0:
        n, t, l = aux_struct(buffer)
        address = t
        segments -= 1
        buffer = buffer[8:]
        
        if   address == 1:
            output['objects'] = []
                        
        elif address == 2:
            pages = l // 2
            output['range'] = []
            
        elif address == 3:
            pages = l // 2
            output['noise'] = []
            
        elif address == 4:
            pages = l // 2
            output['azimuth'] = []
            
        elif address == 5:
            pages = l // 2
            output['doppler'] = []
            
        elif address == 6:
            output['device'] = {}

    # header
    if len(buffer) >= 36 and segments == -1 and address == 0 and pages == 0:
        n, v, l, d, f, t, o, s = aux_head(buffer)
        segments = s
        buffer = buffer[36:]
        output['header'] = {'version': v, 'length': l, 'platform': d, 'number': f, 'time': t, 'objects': o, 'segments': s}
    
    input['buffer'] = buffer
    input['segments'] = segments
    input['address'] = address
    input['pages'] = pages
    input['other'] = other
