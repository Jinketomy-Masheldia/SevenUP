"""Compress a source-rebuilt HC3 and preserve clean IPSW IM4P metadata."""

from .console import say

import ctypes
import hashlib
import plistlib
import tempfile
from pathlib import Path

from .core import digest_file, load_json, publish_directory, require, save_json
from .assets import bootstrap_ticket
from .firmware import resource
from .img4 import children, pack, split_image, ticket_hash, wrap


def compress(data):
    lib = ctypes.CDLL('/usr/lib/libcompression.dylib')
    for name in ['compression_encode_buffer', 'compression_decode_buffer']:
        fn = getattr(lib, name)
        fn.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_int]
        fn.restype = ctypes.c_size_t
    source = ctypes.create_string_buffer(data)
    output = ctypes.create_string_buffer(len(data) + 65536)
    count = lib.compression_encode_buffer(output, len(output), source, len(data), None, 0x891)
    require(0 < count < len(data), 'LZFSE_SMALL compression failed.')
    encoded = output.raw[:count]
    require(encoded.startswith(b'bvx2') and encoded.endswith(b'bvx$'), 'Unexpected LZFSE_SMALL stream.')
    decoded = ctypes.create_string_buffer(len(data))
    length = lib.compression_decode_buffer(decoded, len(data), output, count, None, 0x891)
    require(length == len(data) and decoded.raw == data, 'Native decompression differs from the rebuilt kernel.')
    return encoded


def package(project, raw):
    lock = load_json(project.root / 'profiles/kernel-reference.json')
    data = raw.read_bytes()
    require(len(data) == lock['raw_size'] and hashlib.sha256(data).hexdigest() == lock['raw_sha256'], 'HC3 raw acceptance hash mismatch.')
    source = resource(project, 'ipad_target', 'KernelCache').read_bytes()
    fields = children(source)
    require(len(fields) == 5 and fields[0][1] == b'IM4P' and fields[1][1] == b'krnl' and
            fields[3][0] == 4 and fields[3][1].startswith(b'bvx2'), 'Unexpected original IPSW kernel container.')
    encoded = compress(data)
    payload = pack(0x30, b''.join(pack(0x16, b'rkrn') if i == 1 else pack(4, encoded) if i == 3 else row[2]
                                  for i,row in enumerate(fields)))
    require(hashlib.sha256(payload).hexdigest() == lock['im4p_sha256'],
            'Raw HC3 matches, but compressed IM4P differs. Check compressor/toolchain versions before publishing.')
    capture = project.read_state()['stages'].get('capture')
    if capture:
        ticket = Path(capture['ticket']).read_bytes()
        require(ticket_hash(ticket) == capture['preboot_hash'], 'Captured device IM4M changed.')
        ticket_kind = 'captured-device'
    else:
        ticket = bootstrap_ticket(project)
        ticket_kind = 'temporary-bootstrap-preset'
    image = wrap(payload, ticket)
    digest = hashlib.sha256(image).hexdigest()
    destination = project.work / 'kernel-source' / digest
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix='.pack-', dir=destination.parent))
        path = staging / 'kernelcache.img4'
        path.write_bytes(image)
        try:
            first, second = staging / 'img4-decoded.raw', staging / 'img4tool-decoded.raw'
            project.run([project.tool('img4'), '-i', path, '-o', first])
            project.run([project.tool('img4tool'), '-e', '-o', second, path])
            require(first.read_bytes() == second.read_bytes() == data, 'Independent IMG4 decoders disagree with HC3.')
            require(split_image(path.read_bytes()) == (payload, ticket), 'Final IMG4 metadata or ticket changed.')
            record = {'mode': 'source-rebuilt', 'image': str(destination / 'kernelcache.img4'),
                      'image_hashes': digest_file(path), 'raw_sha256': lock['raw_sha256'],
                      'im4p_sha256': lock['im4p_sha256'], 'clean_rebuild_complete': True,
                      'ticket_kind': ticket_kind, 'raw': str(raw), 'decoder_checks_passed': True}
            save_json(staging / 'receipt.json', record)
            publish_directory(staging, destination)
        except BaseException:
            import shutil
            shutil.rmtree(staging, ignore_errors=True)
            raise
    else:
        record = load_json(destination / 'receipt.json')
        require((destination / 'kernelcache.img4').read_bytes() == image, 'Existing source-built image changed.')
    project.record('kernel', record)
    say('Source-built HC3 accepted: raw kernel and complete compressed IM4P are byte-identical to the reference.', 'success')
    say(f'Generated image: {destination / "kernelcache.img4"}', 'info')
    return record
