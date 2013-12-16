#! python3.3
import preprocessing
import threading
from collections import defaultdict

data = threading.local()
cache = preprocessing.Cache()

def get_preprocessor():
    if not hasattr(data, 'pp'):
        data.pp = preprocessing.Preprocessor(cache)
    return data.pp

def collect_headers(filename, includes, sysincludes, defines, ignored_headers=[]):
    preprocessor = get_preprocessor()
    preprocessor.set_ms_mode(True) # If MSVC.
    preprocessor.set_ms_ext(True) # Should depend on Ze & Za compiler options.
    ppc = preprocessing.PreprocessingContext()
    for path in includes:
        ppc.add_include_path(path, False)
    for path in sysincludes:
        ppc.add_include_path(path, True)
    for define in defines:
        define = define.split('=')
        assert len(define) == 1 or len(define) == 2
        macro = define[0]
        # /Dxxx is actually equivalent to /Dxxx=1.
        value = define[1] if len(define) == 2 else "1"
        ppc.add_macro(macro, value)
    for ignored_header in ignored_headers:
        ppc.add_ignored_header(ignored_header)
    # Group result by dir.
    result = defaultdict(list)
    for dir, name, relative, buff, checksum in preprocessor.scan_headers(ppc, filename):
        result[dir].append([name, relative, buff, checksum])
    return tuple(result.items())

def cache_info():
    return cache.get_stats()

def dump_cache():
    print("Dumping cache.")
    cache.dump('cacheDump.txt')
