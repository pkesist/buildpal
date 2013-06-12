import os
import sys
from multiprocessing import Pool

from utils import TempFile
from msvc import MSVCDistributer
from time import time

def dummy_program(complexity):
    """
        Return long-compiling translation unit contents.
    """
    return """\
    #include <boost/mpl/for_each.hpp>
    #include <boost/mpl/range_c.hpp>

    struct ComputeNothing
    {{
        template <typename N>
        void operator()(N) {{}}
    }};

    template <unsigned complexity>
    void f()
    {{
        using namespace boost::mpl;
        for_each<range_c<unsigned, 0, complexity> >( ComputeNothing() ); 
    }}

    void g()
    {{
        f<100 * {complexity}>();
    }}
    """.format(complexity=complexity)

def compile_cpp(manager, source, object, includes):
    try:
        distributer = MSVCDistributer()
        retcode = distributer.compile_cpp(manager, source, object, includes)
        if retcode != 0:
            print("Retcode is {}".format(retcode))
    except Exception:
        import traceback
        traceback.print_exc()
        raise

if __name__ == "__main__":
    manager = sys.argv[1]
    paralell = int(sys.argv[2])
    tasks = int(sys.argv[3])
    complexity = int(sys.argv[4])

    print("Spawning tasks for manager '{}'".format(manager))
    print("#{} total tasks, #{} paralell".format(tasks, paralell))
    print("Task complexity is {}".format(complexity))

    pool = Pool(processes = paralell)
    boost = r"D:\Sandboxes\PKE\Libraries\Boost\boost_1_53_0"
    
    objs_to_remove = set()
    with TempFile(suffix=".cpp") as tmp:
        with tmp.open('wt') as file:
            file.write(dummy_program(complexity))
        input = tmp.filename()
        start = time()
        for i in range(tasks):
            output = "task{}.obj".format(i)
            objs_to_remove.add(output)
            pool.apply_async(compile_cpp, args=(manager, input, output, [boost]))
        pool.close()
        print("Waiting for tasks...")
        pool.join()
        print("Done, it took {}s".format(time() - start))
        print("Deleting object files...")
        for x in objs_to_remove:
            try:
                os.remove(x)
            except Exception:
                print("Failed to delete '{}'".format(x))

        
