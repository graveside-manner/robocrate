import audiofile
import thumbnail
import os
import os.path
import sys
from samplerate import resample
import wave
import numpy as np
import hashlib
import struct
import config
import random
import eyed3
import json


def _sha1file(filename):
    h = hashlib.sha1()
    with open(filename, 'rb') as file:
        chunk = 0
        while chunk != b'':
            chunk = file.read(1024)
            h.update(chunk)
    return h.hexdigest()


def _scan_file(source):
    """Extract representative audio thumbnails.

    source: a WAV or other music file readable by ffmpeg
    destination: where we will write output
    Output will be a pair of WAV files with arbitrary names, plus matching
    M3U files, where each M3U contains a path to the original input file.
    """
    hash = _sha1file(source)
    signal, frequency = audiofile.read(source)
    # Mix down to a single mono channel.
    if hasattr(signal, 'ndim') and signal.ndim > 1:
        if config.verbose:
            print "  mix to mono"
        signal = signal.mean(axis=1).astype(np.float)
    # Skip anything shorter than 2 minutes
    len_sec = len(signal) / float(frequency)
    if len_sec < 120:
        if config.verbose:
            print "  skip short file (%.2f sec)" % len_sec
        return
    # Resample down to 22.1kHz.
    if frequency > 22050.0:
        if config.verbose:
            print "  downsample to 22050 Hz"
        signal = resample(signal, 22050.0 / frequency, 'sinc_fastest')
        frequency = 22050.0
    if config.verbose:
        print "  analyze"
    left, right = thumbnail.get_pair(signal, frequency, size=30.0)
    if not os.path.isdir(config.dir):
        os.makedirs(config.dir)
    basename = hash
    if config.verbose:
        print "  write " + basename
    # Write an M3U file linking back to the original music file.
    basepath = os.path.join(config.dir, basename)
    with open(basepath + ".m3u", 'w') as fd:
        fd.write(os.path.abspath(source) + os.linesep)
    # Write the clips out as separate WAV files.
    _write_wav16(basepath + "_L.wav", left, frequency)
    _write_wav16(basepath + "_R.wav", right, frequency)
    # Copy interesting ID3 tags out to a JSON file.
    _write_tags(basepath, source)


def _write_wav16(path, signal, frequency):
    data = (signal * np.iinfo(np.int16).max).astype(np.int16)
    wf = wave.open(path, 'wb')
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(int(frequency))
    for s in data:
        wf.writeframesraw(struct.pack('<h', s))
    wf.writeframes('')
    wf.close()


def _write_tags(basepath, source):
    eyed3.log.setLevel("ERROR")
    id3 = eyed3.load(source).tag
    tagnames = [
        "artist", "album_artist", "album", "title", "track_num", "bpm",
        "play_count", "commercial_url", "copyright_url", "audio_file_url",
        "audio_source_url", "artist_url", "internet_radio_url", "payment_url",
        "publisher_url", "album_type", "artist_origin", "comments", "cd_id",
        "encoding_date", "best_release_date", "publisher", "release_date",
        "original_release_date", "recording_date", "tagging_date", "lyrics",
        "disc_num", "popularities", "terms_of_use", "unique_file_ids", "genre",
    ]
    tags = {}
    for name in tagnames:
        if not hasattr(id3, name):
            continue
        val = _id3_val(getattr(id3, name))
        if not val:
            continue
        tags[name] = val
    with open(basepath + "_ID3.json", 'w') as fd:
        json.dump(tags, fd)


def _id3_val(val):
    if not val:
        val = None
    elif isinstance(val, str):
        if 0 == len(val):
            val = None
    elif hasattr(val, '__iter__') and hasattr(val, '__len__'):
        val = [_id3_val(x) for x in val]
        if all(not v for v in val):
            val = None
    if hasattr(val, 'data'):
        val = val.data
    try:
        json.dumps(val)
    except TypeError:
        val = str(val)
    # This appears to be a bug in eyeD3; it sometimes returns strings
    # with a leading \x03, indicating that the contents are UTF-8.
    if isinstance(val, str) and len(val) > 0 and val[0] == '\x03':
        val = val[1:].decode('utf-8')
    return val


def _scan_dir(source):
    if config.verbose:
        print "searching for music files in " + source
    worklist = []
    extensions = tuple(audiofile.extensions())
    exclude = set([config.dir])
    for root, dirs, files in os.walk(source):
        dirs[:] = [d for d in dirs if d not in exclude]
        for file in files:
            if file.endswith(extensions):
                worklist.append(os.path.join(root, file))
    random.shuffle(worklist)
    for i, path in enumerate(worklist):
        relpath = os.path.relpath(path, source)
        printpath = relpath if len(relpath) < len(path) else path
        print "[%d/%d] %s" % (i+1, len(worklist), printpath)
        try:
            _scan_file(path)
        except (IOError), e:
            print e
        except KeyboardInterrupt:
            sys.exit(0)


def scan(source):
    if os.path.isdir(source):
        _scan_dir(source)
    else:
        _scan_file(source)