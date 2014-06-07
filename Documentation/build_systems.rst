``BuildPal`` and some build systems
===================================

`Boost.Build <http://www.boost.org/boost-build2/>`_
---------------------------------------------------

Both approaches will work with Boost.Build.

.. note::

    Currently, Boost.Build has certain limitations when used in distributed
    compilation.

        * It cannot use more than 64 parallel processes (`PR <https://github.com/boostorg/build/pull/5>`__).

        * It runs visual studio setup scripts before every compiler invocation.

            * Since ``MSVC 10.0`` these scripts became excruciatingly slow,
              seriously affecting parallelism (`PR <https://github.com/boostorg/build/pull/6>`__).

    Hopefully both issues wil be resolved soon.


`CMake <http://www.cmake.org>`_
-------------------------------

If you use CMake, prefer generators for build systems which support parallel
tasks, like Ninja and JOM.

MSBuild
-------

MSBuild will not work with :ref:`createprocess_hooking`.
:ref:`compiler_substitution` will work, but the real problem is that MSBuild
does not really have a `-j` option, so it will not utilize the farm. In short -
it does not work well with `BuildPal`, so try to avoid it.

SCons
-----

.. todo::

    Did not try it yet, but most likely works out-of-the-box.