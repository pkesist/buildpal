import os
import re
import sys
import zipfile

import tarfile
import bz2


include = re.compile(r'^\s*#\s*include\s*(?P<stuff>.+)\s*')
easy = re.compile(r'((<)|("))(?P<file>.+)(?(2)>)(?(3)")')

def scan_file(cpp_file, rel_dir, search_path, cache, preprocess, depth=0):
    if depth >= 100:
        print("Reached depth {}, something is wrong".format(depth))
        
    with open(os.path.join(rel_dir, cpp_file), 'rt') as file:
        for line in file.readlines():
            include_match = include.match(line)
            if not include_match:
                continue
            easy_match = easy.match(include_match.group('stuff'))
            if not easy_match:
                raise RuntimeError("Hardball!")
            new_file_name = easy_match.group('file')
            if new_file_name in cache:
                continue
            if easy_match.group(3) == '"':
                rel_cpp_dir = os.path.split(cpp_file)[0]
                rel_file_dir = os.path.join(rel_dir, rel_cpp_dir)
                rel_full_name = os.path.join(rel_cpp_dir, new_file_name)
                abs_full_name = os.path.join(rel_dir, rel_full_name)
                if os.path.exists(abs_full_name):
                    name = os.path.join(rel_cpp_dir, new_file_name)
                    cache[name] = abs_full_name
                    scan_file(rel_full_name, rel_dir, search_path, cache, depth+1)
                    continue

            success = False
            for path in search_path:
                included_file = os.path.join(path, new_file_name)
                if os.path.exists(included_file):
                    cache[new_file_name] = included_file
                    success = True
                    scan_file(new_file_name, path, search_path, cache, depth+1)
                    break
            if not success:
                cache[new_file_name] = None

def collect_headers(cpp_file, rel_dir, search_path, defines, cache, zip_file):
    # Try with the naive approach.
    try:
        for index in range(len(search_path)):
            sp = search_path[index]
            if not os.path.isabs(sp):
                search_path[index] = os.path.join(rel_dir, sp)
        scan_file(cpp_file, rel_dir, search_path, cache, 0)
        with zipfile.ZipFile(zip_file, 'w', zipfile.ZIP_DEFLATED, False) as zip:
            for y in cache:
                zip.write(cache[y], y)
        return True
    except:
        pass

    # Try with our built-in preprocessor
    try:
        import preprocessor
        result = preprocessor.get_all_headers(os.path.join(rel_dir, cpp_file), search_path, defines)
        with zipfile.ZipFile(zip_file, 'w', zipfile.ZIP_DEFLATED, False) as zip:
            for y in result:
                # todo...
                if result[y] is not None:
                    zip.write(result[y], y)
        return True
    except:
        import traceback
        traceback.print_exc()
        pass

    # We failed to collect headers.
    return False