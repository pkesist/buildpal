.. _integrating-with-build-systems:

Integrating ``BuildPal`` with some build systems
================================================

`Boost Build <http://www.boost.org/boost-build2/>`_
---------------------------------------------------

In your :file:`user-config.jam` add (modify) the ``using msvc`` directive like so:

.. code-block:: jam

    local compiler = "c:\\Path\\To\\bp_cl.exe" ;
    using msvc : 9.0 : : <compiler>$(compiler) ;

You can add a command line option for ``b2`` to turn on distributed build when
needed:

.. code-block:: jam

    if --distributed in [ modules.peek : ARGV ]
    {
        local compiler = "c:\\Path\\To\\bp_cl.exe" ;

        using msvc : 9.0 : : <compiler>$(compiler) ;
        using msvc : 10.0 : : <compiler>$(compiler) ;
    }
    else
    {
        using msvc : 9.0 ;
        using msvc : 10.0 ;
    }

.. note::

    Currently, Boost.Build has certain limitations when used in distributed
    compilation.

        * It cannot use more than 64 paralell processes (`PR <https://github.com/boostorg/build/pull/5>`__).

        * It runs visual studio setup scripts before every compiler invocation.

            * Since ``MSVC 10.0`` these scripts became excruciatingly slow,
              seriously affecting paralellism (`PR <https://github.com/boostorg/build/pull/6>`__).

    Hopefully both issues wil be resolved soon.


`CMake <http://www.cmake.org>`_
-------------------------------

.. todo::

    Add CMake integration information.

Visual Studio Build
-------------------

.. todo::

    Add Visual Studio integration information. See how ``clang-cl`` did that.
    We will probably need to rename the executable to :file:`cl.exe` and tinker
    with ``PATH``.


