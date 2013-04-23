from utils import TempFile

import os
import zipfile

def collect_headers(cpp_file, rel_dir, search_path, defines, cache):
    try:
        import preprocessor
        result = preprocessor.get_all_headers(os.path.join(rel_dir, cpp_file), search_path, defines)
        zip_file = TempFile(suffix='.zip')
        with zipfile.ZipFile(zip_file.filename(), 'w', zipfile.ZIP_DEFLATED, False) as zip:
            for y in result:
                # todo...
                if result[y] is not None:
                    zip.write(result[y], y)
        return zip_file
    except:
        import traceback
        traceback.print_exc()
        pass

    # We failed to collect headers.
    return None