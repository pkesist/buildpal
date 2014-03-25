import sys
import urllib.request
import zipfile
import os

from io import BytesIO

def unpack_zip(zip_buffer, target_dir, remove_top_path=True):
    print("Extracting to '{}'...".format(target_dir))
    os.makedirs(target_dir, exist_ok=True)
    with zipfile.ZipFile(zip_buffer) as zip:
        prefix = ''
        total = len(zip.infolist())
        count = 0
        lastlen = 0
        for zip_info in zip.infolist():
            count += 1
            path = zip_info.filename
            # Make sure we overwrite old output with spaces.
            if len(path) < lastlen:
                path += ' ' * (lastlen - len(path))
            lastlen = len(path)
            sys.stdout.write('[{}/{}] {:128}\r'.format(count, total, path))
            if remove_top_path and not prefix:
                prefix = zip_info.filename[:path.index('/') + 1]
            assert zip_info.filename[:len(prefix)] == prefix
            remainder = zip_info.filename[len(prefix):]
            if not remainder or remainder.endswith('/'): continue
            target_path = os.path.join(target_dir, remainder)
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            with open(target_path, 'wb') as file:
                file.write(zip.read(zip_info))
        print()

def get_zip(url, target_dir, cache_dir, cache_filename=None, remove_top_path=True):
    if not cache_filename:
        cache_filename = url.split('/')[-1]
    cache_file = os.path.join(cache_dir, cache_filename)
    if not os.path.isfile(cache_file):
        print("Downloading '{}'...".format(url))
        req = urllib.request.urlopen(url)
        buffer = BytesIO()
        try:
            length = int(req.headers['content-length'])
        except Exception:
            length = None
        got = 0
        for data in iter(lambda : req.read(128 * 1024), b''):
            got += len(data)
            if length is not None:
                sys.stdout.write("Progress: {:.1f}%\r".format(got * 100/length))
            else:
                sys.stdout.write("Progress: {} bytes\r".format(got))
            buffer.write(data)
        buffer.seek(0)
        os.makedirs(os.path.dirname(cache_file), exist_ok=True)
        with open(cache_file, 'wb') as file:
            file.write(buffer.read())
    else:
        buffer = BytesIO()
        with open(cache_file, 'rb') as file:
            buffer.write(file.read())
    buffer.seek(0)
    unpack_zip(buffer, target_dir, remove_top_path)

def get_from_github(project_info, target_dir, cache_dir):
    url = 'https://github.com/{user}/{repo}/archive/{branch}.zip'.format(**project_info)
    get_zip(url, target_dir, cache_dir, cache_filename='{repo}-{branch}.zip'.format(**project_info))

