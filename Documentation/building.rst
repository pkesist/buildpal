Building ``BuildPal``
=====================

.. _setuptools: http://pypi.python.org/pypi/setuptools

In order to build ``BuildPal`` you need:

    * ``Python 3.4`` (with setuptools_)
    * ``Visual C++ 2012 (11.0)``
    
Other dependencies will be downloaded and built automatically. setuptools_
comes bundled with Python 3.4. If it is missing for some reason you can easily
install it by running::

    python -m ensurepip


Get the sources from GitHub
---------------------------

Get the sources from `BuildPal GitHub repository <https://github.com/pkesist/buildpal>`_.

Building
--------

`BuildPal` uses distutils and setuptools. Just use any of the usual setuptools
targets::

    python setup.py build
    python setup.py install
    python setup.py develop
    ...

See ``python setup.py --help``

.. note::

    First time build will take a while. BuildPal will download, unpack and build
    several chubby libraries (`Boost` and `LLVM/Clang`). Subsequent builds will be
    much faster.

.. _cx-freeze::

Creating standalone packages with ``cx_Freeze``
-----------------------------------------------

.. _cx_Freeze: http://cx-freeze.sourceforge.net/

Usually, you want to avoid installing Python on every machine on the build farm.
For this you can create an stand-alone distribution package with
cx_Freeze_.


* Install cx_Freeze_.

.. note::

    You need to use cx_Freeze_ 4.3.3 or newer. Previous releases do not support
    Python 3.4 very well. In addition, if cx_Freeze release is not built for
    your exact Python release (including minor version), there is a good chance
    that the executable it produces will not work. If this happens, you need to
    build cx_Freeze yourself.

* Do either ``setup.py install`` or ``setup.py develop``.
* Run ``cx_freeze_setup.py bdist_msi``

