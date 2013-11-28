#! python3.3
import preprocessing
import threading

data = threading.local()
cache = preprocessing.Cache()
caches = {cache}

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
        value = define[1] if len(define) == 2 else ""
        ppc.add_macro(macro, value)
    for ignored_header in ignored_headers:
        ppc.add_ignored_header(ignored_header)
    return preprocessor.scan_headers(ppc, filename)

def cache_info():
    stats = list(cache.get_stats() for cache in caches)
    return (sum(hits for hits, _ in stats), sum(misses for _, misses in stats))

def dump_cache():
    counter = 0
    for cache in caches:
        cache.dump('cacheDump{}.txt'.format(counter))
        counter += 1
